import streamlit as st
from google import genai
from google.genai import types
import requests

# 1. 페이지 및 스타일 설정 (넓은 화면 배치)
st.set_page_config(page_title="단어 카테고리 & 인기 영상 추출기", layout="wide")

st.title("🎯 핵심 카테고리 및 유튜브 25개 영상 추출기")
st.caption("단어를 분석하여 카테고리를 분류하고, 유튜브 인기 영상 25개 중 크리에이티브 커먼즈(CC) 라이선스 영상을 찾아 표시합니다.")
st.divider()

# 2. 내부 Secrets 시스템에서 API 키 자동 로드
gemini_api_key = st.secrets.get("GEMINI_API_KEY", None)
youtube_api_key = st.secrets.get("YOUTUBE_API_KEY", None)

# 유튜브 API 호출 함수 (25개 수집 후 내부 CC 라이선스 판별)
def get_youtube_videos_with_cc_label(query, api_key, target_count=25):
    if not api_key:
        return None
    
    long_videos = []
    shorts_videos = []
    
    search_url = "https://www.googleapis.com/youtube/v3/search"
    search_params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",  # 순수 조회수 높은 순서대로 수집
        "maxResults": 50,      # 필터링 후 양쪽 25개를 맞추기 위해 넉넉히 수집
        "key": api_key
    }
        
    try:
        search_response = requests.get(search_url, params=search_params).json()
        items = search_response.get("items", [])
        
        if not items:
            return [], []
            
        video_ids = [item["id"]["videoId"] for item in items]
        
        # 라이선스(status) 정보까지 한 번에 요청
        video_url = "https://www.googleapis.com/youtube/v3/videos"
        video_params = {
            "part": "snippet,statistics,contentDetails,status",
            "id": ",".join(video_ids),
            "key": api_key
        }
        video_response = requests.get(video_url, params=video_params).json()
        
        for item in video_response.get("items", []):
            stats = item.get("statistics", {})
            view_count = int(stats.get("viewCount", 0))
            
            # 기준: 조회수 10만 이상 필터링
            if view_count >= 100000:
                title = item["snippet"]["title"]
                video_id = item["id"]
                url = f"https://www.youtube.com/watch?v={video_id}"
                duration = item["contentDetails"]["duration"]
                
                # 영상 라이선스 확인 ('creativeCommon'인 경우 True)
                license_type = item.get("status", {}).get("license", "youtube")
                is_cc = (license_type == "creativeCommon")
                
                # 조회수 단위 가독성 처리
                if view_count >= 100000000:
                    view_str = f"{view_count / 100000000:.1f}억회"
                else:
                    view_str = f"{view_count // 10000}만회"
                    
                video_data = {
                    "title": title,
                    "view_count": view_str,
                    "url": url,
                    "is_cc": is_cc  # CC 여부 저장
                }
                
                # 롱폼 / 쇼츠 판정 (1분 미만 여부 체크)
                if "M" not in duration and "H" not in duration:
                    if len(shorts_videos) < target_count:
                        shorts_videos.append(video_data)
                elif "PT1M" in duration and duration.endswith("S") and int(duration.split("M")[1].replace("S","")) == 0:
                    if len(shorts_videos) < target_count:
                        shorts_videos.append(video_data)
                elif "PT0M" in duration:
                    if len(shorts_videos) < target_count:
                        shorts_videos.append(video_data)
                else:
                    if len(long_videos) < target_count:
                        long_videos.append(video_data)
                        
    except Exception as e:
        st.error(f"유튜브 수집 중 에러 발생: {e}")
        
    return long_videos, shorts_videos

# 3. 메인 입력창
st.subheader("📝 분석할 단어 입력")
user_input = st.text_input(
    "분석할 단어를 입력하세요.",
    placeholder="예시: 챗GPT, 자율주행, 비트코인, 오마카세 등..."
)

# 4. 분석 로직 트리거
if st.button("🚀 분석 및 인기 영상 추출 시작"):
    if not gemini_api_key:
        st.error("🔑 Gemini API Key가 Secrets에 설정되지 않았습니다.")
    elif user_input.strip() == "":
        st.warning("📝 분석할 단어를 입력해 주세요.")
    else:
        # 화면 좌우 2분할 설정
        col_analysis, col_youtube = st.columns([1, 1.5])
        
        # [왼쪽 열] Gemini 카테고리 + 키워드 + 해시태그 분석
        with col_analysis:
            with st.spinner("Gemini가 단어와 해시태그를 분석하는 중..."):
                try:
                    client = genai.Client(api_key=gemini_api_key)
                    
                    system_instruction = """
                    당신은 입력된 단어의 핵심 내용을 정확히 파악하여 카테고리, 핵심 키워드, SNS용 연관 해시태그를 추출하는 전문가입니다.
                    반드시 다음 규칙을 엄격하게 준수하여 결과를 출력해야 합니다. 불필요한 서론이나 설명은 절대 제외하세요.

                    [카테고리 선정 우선순위 (대분류 후보)]
                    - 의료/건강, IT/기술, 경제/금융, 정치/사회, 교육, 문화/예술, 엔터테인먼트, 스포츠, 여행, 음식, 동물, 생활/주방, 자동차, 게임, 법률, 과학, 역사, 종교, 기타

                    [규칙]
                    1. 대분류는 우선순위 리스트 중 1개만 선택.
                    2. 소분류는 세부 주제 카테고리 2~3개 제시.
                    3. 키워드는 중요도 순으로 나열하며 최대 10개 추출.
                    4. 해시태그는 Instagram, YouTube Shorts 등에서 사용하기 좋은 트렌디한 연관 키워드를 단어 앞에 '#'를 붙여 최대 10개까지 추출한다.
                    5. 중복 표현 제거 및 불필요한 설명 금지.
                    6. 응답은 반드시 아래 형식을 정확히 따른다.

                    [출력 형식]
                    - 대분류: 상위 카테고리
                    - 소분류: 카테고리1, 카테고리2, 카테고리3
                    - 키워드: 키워드1, 키워드2, 키워드3
                    - 해시태그: #해시태그1 #해시태그2 #해시태그3
                    """

                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=f"다음 단어를 규칙에 맞게 추출해줘:\n\n{user_input}",
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.1
                        )
                    )
                    st.success("🎯 분석 완료!")
                    st.code(response.text, language="text")
                except Exception as e:
                    st.error(f"Gemini 에러: {e}")
        
        #
