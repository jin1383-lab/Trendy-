import streamlit as st
from google import genai
from google.genai import types
import requests

# 1. 페이지 및 스타일 설정
st.set_page_config(page_title="단어 카테고리 & 인기 영상 추출기", layout="wide")

st.title("🎯 핵심 카테고리 및 유튜브 인기 영상 추출기")
st.caption("단어를 분석하여 카테고리를 분류하고, 유튜브에서 조회수 10만/50만 이상의 롱폼 및 쇼츠 영상을 추출합니다.")
st.divider()

# 2. 내부 Secrets 시스템에서 API 키 자동 로드
gemini_api_key = st.secrets.get("GEMINI_API_KEY", None)
youtube_api_key = st.secrets.get("YOUTUBE_API_KEY", None)

# 유튜브 API 호출 함수 (조회수 정렬 및 영상 길이 기반 롱폼/쇼츠 분류)
def get_youtube_videos(query, api_key):
    if not api_key:
        return None
    
    # 1단계: 검색어 기준 대중성/조회수 순으로 영상 25개 검색
    search_url = "https://www.googleapis.com/youtube/v3/search"
    search_params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "maxResults": 25,
        "key": api_key
    }
    
    try:
        search_response = requests.get(search_url, params=search_params).json()
        video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
        
        if not video_ids:
            return [], []
            
        # 2단계: 검색된 영상들의 상세 정보(조회수, 영상 길이) 가져오기
        video_url = "https://www.googleapis.com/youtube/v3/videos"
        video_params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": api_key
        }
        video_response = requests.get(video_url, params=video_params).json()
        
        long_videos = []
        shorts_videos = []
        
        for item in video_response.get("items", []):
            stats = item.get("statistics", {})
            view_count = int(stats.get("viewCount", 0))
            
            # 기준: 조회수 10만 이상만 필터링 (원하는 대로 조정 가능)
            if view_count >= 100000:
                title = item["snippet"]["title"]
                video_id = item["id"]
                url = f"https://www.youtube.com/watch?v={video_id}"
                duration = item["contentDetails"]["duration"] # ISO 8601 포맷 (예: PT45S, PT15M)
                
                video_data = {
                    "title": title,
                    "view_count": f"{view_count // 10000}만회",
                    "url": url
                }
                
                # 유튜브 API 기준 영상 길이 분석 (M이 없고 S만 있거나, 1분 미만인 경우 쇼츠로 판단)
                if "M" not in duration and "H" not in duration:
                    shorts_videos.append(video_data)
                elif "PT1M" in duration and duration.endswith("S") and int(duration.split("M")[1].replace("S","")) == 0:
                    shorts_videos.append(video_data) # 딱 1분
                    # 일반적으로 대략적인 문자열 패턴 매칭 적용
                elif "PT0M" in duration or ("M" not in duration):
                    shorts_videos.append(video_data)
                else:
                    long_videos.append(video_data)
                    
        return long_videos, shorts_videos
    except Exception as e:
        st.error(f"유튜브 데이터 로드 실패: {e}")
        return [], []

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
        # 화면을 좌우 2분할하여 결과 배치
        col_analysis, col_youtube = st.columns([1, 1])
        
        # [왼쪽 열] Gemini 카테고리 분석
        with col_analysis:
            with st.spinner("Gemini가 단어를 분석하는 중..."):
                try:
                    client = genai.Client(api_key=gemini_api_key)
                    
                    system_instruction = """
                    당신은 입력된 단어의 핵심 내용을 정확히 파악하여 카테고리와 핵심 키워드를 추출하는 전문가입니다.
                    반드시 다음 규칙을 엄격하게 준수하여 결과를 출력해야 합니다. 불필요한 서론이나 설명은 절대 제외하세요.

                    [카테고리 선정 우선순위 (대분류 후보)]
                    - 의료/건강, IT/기술, 경제/금융, 정치/사회, 교육, 문화/예술, 엔터테인먼트, 스포츠, 여행, 음식, 동물, 생활/주방, 자동차, 게임, 법률, 과학, 역사, 종교, 기타

                    [규칙]
                    1. 대분류는 우선순위 리스트 중 1개만 선택.
                    2. 소분류는 세부 주제 카테고리 2~3개 제시.
                    3. 키워드는 중요도 순으로 나열하며 최대 10개 추출.
                    4. 중복 표현 제거 및 불필요한 설명 금지.
                    5. 응답은 반드시 아래 형식을 정확히 따른다.

                    [출력 형식]
                    - 대분류: 상위 카테고리
                    - 소분류: 카테고리1, 카테고리2, 카테고리3
                    - 키워드: 키워드1, 키워드2, 키워드3
                    """

                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=f"다음 단어를 규칙에 맞게 추출해줘:\n\n{user_input}",
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.1
                        )
                    )
                    st.success("🎯 카테고리 분석 완료!")
                    st.code(response.text, language="text")
                except Exception as e:
                    st.error(f"Gemini 에러: {e}")
        
        # [오른쪽 열] 유튜브 실시간 인기 영상 매칭
        with col_youtube:
            if not youtube_api_key:
                st.info("📢 유튜브 API Key를 등록하면 실시간 인기 영상 조회가 활성화됩니다.")
            else:
                with st.spinner("유튜브에서 조회수 10만 이상 영상 찾는 중..."):
                    long_videos, shorts_videos = get_youtube_videos(user_input, youtube_api_key)
                    
                    st.success("📺 유튜브 인기 영상 매칭 완료!")
                    
                    # 탭 분할 (롱폼 / 쇼츠)
                    tab1, tab2 = st.tabs(["🎥 롱폼 영상 (조회수 10만↑)", "📱 쇼츠 영상 (조회수 10만↑)"])
                    
                    with tab1:
                        if long_videos:
                            for vid in long_videos[:5]: # 상위 5개 출력
                                st.markdown(f"**[{vid['title']}]({vid['url']})**")
                                st.caption(f"🔥 조회수: {vid['view_count']}")
                        else:
                            st.write("조건에 맞는 대형 롱폼 영상이 없습니다.")
                            
                    with tab2:
                        if shorts_videos:
                            for vid in shorts_videos[:5]: # 상위 5개 출력
                                st.markdown(f"**[{vid['title']}]({vid['url']})**")
                                st.caption(f"🔥 조회수: {vid['view_count']}")
                        else:
                            st.write("조건에 맞는 대형 쇼츠 영상이 없습니다.")
