import streamlit as st
from google import genai
from google.genai import types
import requests
import time

# 1. 페이지 및 스타일 설정 (넓은 화면 배치)
st.set_page_config(page_title="단어 카테고리 & 인기 영상 추출기", layout="wide")

st.title("🎯 핵심 카테고리 및 유튜브 25개 영상 추출기")
st.caption("단어를 분석하여 카테고리를 분류하고, 유튜브 인기 영상 중 크리에이티브 커먼즈(CC) 라이선스 영상을 찾아 표시합니다.")
st.divider()

# 2. 내부 Secrets 시스템에서 API 키 자동 로드
gemini_api_key = st.secrets.get("GEMINI_API_KEY", None)
youtube_api_key = st.secrets.get("YOUTUBE_API_KEY", None)

# 유튜브 API 호출 함수 (CC 검출 확률을 높이기 위해 검색 모풀을 50개로 유지)
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
        "maxResults": 50,      # 상위 50개 풀을 조사하여 CC가 있는지 샅샅이 뒤집니다.
        "key": api_key
    }
        
    try:
        search_response = requests.get(search_url, params=search_params).json()
        items = search_response.get("items", [])
        
        if not items:
            return [], []
            
        video_ids = [item["id"]["videoId"] for item in items]
        
        # 라이선스(status) 정보 정밀 요청
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
                
                # 영상 라이선스 확인 (대소문자 구분 없이 정확하게 매칭)
                license_type = item.get("status", {}).get("license", "youtube")
                is_cc = (license_type.lower() == "creativecommon")
                
                # 조회수 단위 가독성 처리
                if view_count >= 100000000:
                    view_str = f"{view_count / 100000000:.1f}억회"
                else:
                    view_str = f"{view_count // 10000}만회"
                    
                video_data = {
                    "title": title,
                    "view_count": view_str,
                    "url": url,
                    "is_cc": is_cc
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

                    response = None
                    for attempt in range(3):
                        try:
                            response = client.models.generate_content(
                                model='gemini-2.5-flash',
                                contents=f"다음 단어를 규칙에 맞게 추출해줘:\n\n{user_input}",
                                config=types.GenerateContentConfig(
                                    system_instruction=system_instruction,
                                    temperature=0.1
                                )
                            )
                            break
                        except Exception as e:
                            if "503" in str(e) and attempt < 2:
                                time.sleep(2)
                                continue
                            else:
                                raise e

                    if response:
                        st.success("🎯 분석 완료!")
                        st.code(response.text, language="text")
                
                except Exception as e:
                    if "503" in str(e) or "UNAVAILABLE" in str(e):
                        st.error("⏳ 구글 Gemini 서버의 순간 트래픽이 너무 높습니다. 잠시 후 버튼을 다시 눌러주세요!")
                    else:
                        st.error(f"Gemini 에러: {e}")
        
        # [오른쪽 열] 유튜브 분석 결과 출력
        with col_youtube:
            if not youtube_api_key:
                st.info("📢 유튜브 API Key를 등록하면 실시간 인기 영상 조회가 활성화됩니다.")
            else:
                with st.spinner("유튜브에서 인기 영상을 수집하고 라이선스를 판별하는 중..."):
                    long_videos, shorts_videos = get_youtube_videos_with_cc_label(user_input, youtube_api_key, target_count=25)
                    
                    st.success(f"📺 수집 완료! (롱폼: {len(long_videos)}개 / 쇼츠: {len(shorts_videos)}개)")
                    
                    tab1, tab2 = st.tabs([f"🎥 롱폼 리스트 ({len(long_videos)}개)", f"📱 쇼츠 리스트 ({len(shorts_videos)}개)"])
                    
                    # CC 유무를 시각적으로 카운트하기 위한 변수
                    cc_long_count = sum(1 for v in long_videos if v["is_cc"])
                    cc_shorts_count = sum(1 for v in shorts_videos if v["is_cc"])
                    
                    with tab1:
                        if cc_long_count > 0:
                            st.info(f"💡 현재 리스트에 {cc_long_count}개의 [CC] 영상이 포함되어 있습니다.")
                        else:
                            st.caption("ℹ️ 조회수가 높은 상위 영상 중 CC 라이선스 영상이 없습니다. (모두 표준 유튜브 라이선스)")
                            
                        if long_videos:
                            for i, vid in enumerate(long_videos, 1):
                                if vid["is_cc"]:
                                    expander_title = f"{i}. {vid['title']} ({vid['view_count']}) [CC]"
                                else:
                                    expander_title = f"{i}. {vid['title']} ({vid['view_count']})"
                                    
                                with st.expander(expander_title):
                                    if vid["is_cc"]:
                                        st.success("ℹ️ **크리에이티브 커먼즈(CC-BY) 라이선스 영상입니다.** 출처 표기 시 재사용 및 수정 편집이 가능합니다.")
                                    st.markdown(f"🔗 [유튜브에서 영상 보기]({vid['url']})")
                        else:
                            st.write("조건에 맞는 대형 롱폼 영상이 검색되지 않았습니다.")
                            
                    with tab2:
                        if cc_shorts_count > 0:
                            st.info(f"💡 현재 리스트에 {cc_shorts_count}개의 [CC] 영상이 포함되어 있습니다.")
                        else:
                            st.caption("ℹ️ 조회수가 높은 상위 영상 중 CC 라이선스 영상이 없습니다. (모두 표준 유튜브 라이선스)")
                            
                        if shorts_videos:
                            for i, vid in enumerate(shorts_videos, 1):
                                if vid["is_cc"]:
                                    expander_title = f"{i}. {vid['title']} ({vid['view_count']}) [CC]"
                                else:
                                    expander_title = f"{i}. {vid['title']} ({vid['view_count']})"
                                    
                                with st.expander(expander_title):
                                    if vid["is_cc"]:
                                        st.success("ℹ️ **크리에이티브 커먼즈(CC-BY) 라이선스 영상입니다.** 출처 표기 시 재사용 및 수정 편집이 가능합니다.")
                                    st.markdown(f"🔗 [유튜브에서 쇼츠 보기]({vid['url']})")
                        else:
                            st.write("조건에 맞는 대형 쇼츠 영상이 검색되지 않았습니다.")
