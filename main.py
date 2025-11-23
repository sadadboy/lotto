import os
import sys
from dotenv import load_dotenv
from loguru import logger
from auth import login

# 환경 변수 로드
load_dotenv()

def main():
    # 암호화된 환경 변수 로드
    encrypted_id = os.getenv("LOTTO_USER_ID")
    encrypted_pw = os.getenv("LOTTO_USER_PW")

    if not encrypted_id or not encrypted_pw:
        logger.error("아이디 또는 비밀번호가 설정되지 않았습니다. 'python setup_auth.py'를 실행하여 설정해주세요.")
        return

    # 복호화
    from security import SecurityManager
    manager = SecurityManager()
    user_id = manager.decrypt(encrypted_id)
    user_pw = manager.decrypt(encrypted_pw)

    if not user_id or not user_pw:
        logger.error("계정 정보 복호화 실패. 'secret.key'가 변경되었거나 파일이 손상되었습니다. 'python setup_auth.py'를 다시 실행해주세요.")
        return

    logger.info("로또 자동 구매 프로그램 시작")
    
    # 로그인 테스트
    try:
        browser, page = login(user_id, user_pw)
        logger.success("로그인 성공! (브라우저가 열려있습니다)")
        
        # 2단계: 구매 로직 테스트
        import lotto
        
        # 예치금 확인
        lotto.check_deposit(page)
        
        # 구매 페이지 이동
        # 주의: go_to_lotto_page가 현재 페이지를 이동시키는지, 새 팝업을 여는지에 따라 처리 달라짐
        # 현재 구현은 goto로 이동함
        lotto.go_to_lotto_page(page)
        
        # 잠시 대기 (로딩)
        import time
        time.sleep(3)
        
        # 3단계: 전략 기반 구매
        import analysis
        
        # 전략 설정 (환경 변수 또는 기본값)
        # auto: 사이트 자동선택 (AI 추천?)
        # hot: 과거 당첨 많이 된 번호
        # cold: 과거 당첨 적게 된 번호
        strategy = os.getenv("LOTTO_STRATEGY", "hot").lower()
        
        if strategy == "auto":
            logger.info(">>> 전략: AI 추천 (사이트 자동선택) <<<")
            logger.info("사이트의 '자동번호발급' 기능을 사용합니다.")
            lotto.select_auto_numbers(page, quantity=1)
            
        else:
            if strategy == "hot":
                logger.info(">>> 전략: 과거 1등 번호 기반 (Hot) <<<")
                logger.info("최근 당첨번호를 분석하여 가장 많이 나온 번호를 조합합니다.")
            elif strategy == "cold":
                logger.info(">>> 전략: 과거 미출현 번호 기반 (Cold) <<<")
                logger.info("최근 당첨번호를 분석하여 가장 적게 나온 번호를 조합합니다.")
            else:
                logger.warning(f"알 수 없는 전략 '{strategy}'. 기본값(Hot)으로 진행합니다.")
                strategy = "hot"

            # 최근 10회차 데이터 수집
            history = analysis.fetch_recent_history(limit=10)
            
            # 전략에 따른 번호 생성
            numbers = analysis.generate_numbers(strategy=strategy, history=history)
            logger.info(f"생성된 추천 번호: {numbers}")
            
            # 생성된 번호로 수동 선택
            lotto.select_manual_numbers(page, numbers)

        time.sleep(1)
        
        # 구매 (Dry Run)
        lotto.buy_lotto(page, dry_run=True)
        
        # 테스트를 위해 잠시 대기
        input("엔터를 누르면 종료합니다...")
        
        browser.close()
    except Exception as e:
        logger.error(f"실행 중 오류 발생: {e}")
        if 'browser' in locals():
            browser.close()

if __name__ == "__main__":
    main()
