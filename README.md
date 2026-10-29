# 40대 남성 아침 브리핑

매일 07:30(KST), 지난 24시간 기사(약 60건) 중 40대 남성에게 쓸모 있는 **10건**을 남성복·스포츠·화장품으로 나눠 골라 한국어로 요약해 Discord로 보내는 뉴스레터 에이전트예요. 파트마다 3건씩 기본으로 받고, 남은 1자리(와 모자란 파트의 빈자리)는 그날 가장 좋은 후보가 있는 파트가 가져가요. GitHub Actions가 OpenAI API로 만들어 보내요. [ai-newsletter-agent](https://github.com/Lightnine999/ai-newsletter-agent)와 같은 구조로 만들었어요.

```
START → collect → select ─(Send × 10)→ report → verify → publish → END
        피드 17개   3·3·3 + 결승 1     세 칸 요약   원문 대조   Discord
```

| 노드 | 하는 일 |
|---|---|
| collect | RSS·Atom 피드 17개(매체 14곳)에서 24시간 글. 추적 꼬리표만 떼고 중복 제거, 이미 보낸 주소 제외, 막힌 소스는 로그에 |
| select | LLM이 파트 배정 → 파트별 순위 → 후보가 적은 파트부터 3건씩 → 결승으로 남은 자리. 파트 안 같은 매체 2건, 전체 3건까지 |
| report | 기사마다 워커. 본문 600자 미만은 빼고, 제목·요약·40대에게 왜 세 칸. 영어면 한 번 다시 쓰기 |
| verify | 따로 부른 LLM이 제목·요약을 원문과 대조. 떨어진 자리는 예비 후보로 한 번씩 교체 |
| publish | 배분 한 줄 + 파트별 카드 메시지. 보낸 날은 `issues/날짜.md`와 `store/sent.jsonl`에 기록 |

## 실행

```bash
uv venv && uv pip install -r requirements.txt pytest
cp .env.example .env                 # OPENAI_API_KEY, DISCORD_WEBHOOK_URL 채우기
.venv/bin/python -m pytest -q        # 실제 API·네트워크 없이 돌아요
.venv/bin/python run.py --dry-run    # 보내지 않고 로그와 output/날짜.md만
DRY_RUN=0 .venv/bin/python run.py    # 실제 발송 (오늘 이미 보냈으면 건너뜀)
```

GitHub Actions(`.github/workflows/daily.yml`)는 07:30 + 예비 07:50·08:10에 돌고, 저장소 Secrets의 `OPENAI_API_KEY`·`DISCORD_WEBHOOK_URL`을 써요. 보내지 못하면 빨간불(exit 1)이 되고, 보낸 기록은 저장소에 커밋해요.

## 문서

| 문서 | 내용 |
|---|---|
| [REPORT.md](REPORT.md) | **수행 결과 보고서** (분야·독자, 소스 채택표, 선별 로직, 구조도, 실행 기록, 회고) |
| [PRD.md](PRD.md) | 요구사항 (제품 개요 + 1부~7부 + 정리) |
| [docs/plan.md](docs/plan.md) | 1부~7부 진행 기록과 실측 결과 |
| [docs/sources.md](docs/sources.md) | 다섯 길 비교, 소스 관문(G1~G3) 측정, 뺀 곳 재점검 |
| [prompts/newsletter.md](prompts/newsletter.md) | 노드별 프롬프트 설계 |
| [audience.yaml](audience.yaml) | 독자·파트·10건 배분·기준·제외 조건·소스 — 코드를 안 고치고 여기만 바꿔요 |
| [issues/](issues/) | 보낸 브리핑 사본 (0호: 손으로 만든 기준선) |

소스·키워드 원본 명세(`sources-master.docx`)와 따라간 교재(`D00_뉴스레터_노드_완전판.html`)는 로컬에만 둬요.
