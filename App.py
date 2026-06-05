import streamlit as st
from google import genai
from google.genai import types

# 1. 페이지 및 스타일 설정
st.set_page_config(page_title="단어 카테고리 & 키워드 추출기", layout="centered")

st.title("🎯 핵심 카테고리 및 키워드 추출기")
st.caption("단어를 분석하여 정해진 규칙에 따라 대분류, 소분류, 키워드를 추출합니다.")
st.divider()

# 2. 내부 Secrets 시스템에서 Gemini API 키 자동 로드
if "GEMINI_API_KEY" in st.secrets:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
else:
    gemini_api_key = None

# 3. 메인 입력창 (한 줄 입력창 st.text_input 으로 변경)
st.subheader("📝 분석할 단어 입력")
user_input = st.text_input(
    "분석할 단어를 입력하세요.",
    placeholder="예시: 챗GPT, 자율주행, 비트코인, 오마카세 등..."
)

# 4. 분석 로직 트리거
if st.button("🚀 분석 시작"):
    if not gemini_api_key:
        st.error("🔑 API Key를 찾을 수 없습니다. Streamlit 세팅(Secrets)이나 .streamlit/secrets.toml 파일에 'GEMINI_API_KEY'를 설정해 주세요.")
    elif user_input.strip() == "":
        st.warning("📝 분석할 단어를 입력해 주세요.")
    else:
        with st.spinner("Gemini가 단어의 맥락을 분석하고 규칙을 적용하는 중..."):
            try:
                # 구글 최신 표준 genai 클라이언트 초기화
                client = genai.Client(api_key=gemini_api_key)
                
                # 시스템 지시사항(프롬프트) 설정
                system_instruction = """
                당신은 입력된 단어의 핵심 내용을 정확히 파악하여 카테고리와 핵심 키워드를 추출하는 전문가입니다.
                반드시 다음 규칙을 엄격하게 준수하여 결과를 출력해야 합니다. 불필요한 서론이나 설명은 절대 제외하세요.

                [카테고리 선정 우선순위 (대분류 후보)]
                - 의료/건강
                - IT/기술
                - 경제/금융
                - 정치/사회
                - 교육
                - 문화/예술
                - 엔터테인먼트
                - 스포츠
                - 여행
                - 음식
                - 동물
                - 생활/주방
                - 자동차
                - 게임
                - 법률
                - 과학
                - 역사
                - 종교
                - 기타

                [규칙]
                1. 대분류는 [카테고리 선정 우선순위] 리스트에 있는 항목 중 텍스트가 속하는 가장 포괄적인 상위 카테고리 딱 1개만 선택한다.
                2. 소분류는 세부 주제를 나타내는 카테고리 2~3개를 제시한다.
                3. 키워드는 중요도 순으로 나열하며, 최대 10개까지 추출한다.
                4. 키워드는 명사, 고유명사, 주요 개념, 전문 용어 위주로 추출한다.
                5. 중복 표현은 제거한다.
                6. 불필요한 설명은 제외한다.
                7. 입력 텍스트가 매우 짧더라도 문맥을 통해 가장 적절한 카테고리를 추론한다.
                8. 응답은 반드시 아래 형식을 정확히 따른다. 대괄호([])는 제거하고 알맞은 값만 채운다.

                [출력 형식]
                - 대분류: 상위 카테고리
                - 소분류: 카테고리1, 카테고리2, 카테고리3
                - 키워드: 키워드1, 키워드2, 키워드3
                """

                # Gemini API 호출
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"다음 단어를 규칙에 맞게 추출해줘:\n\n{user_input}",
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.1
                    )
                )
                
                result_text = response.text
                
                # 결과 화면 출력
                st.success("🎯 분석 완료!")
                st.subheader("📊 추출 결과")
                
                # 텍스트 박스 형태로 깔끔하게 렌더링
                st.code(result_text, language="text")

            except Exception as e:
                st.error(f"❌ 오류가 발생했습니다: {e}")
