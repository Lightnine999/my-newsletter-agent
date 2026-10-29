# 자료를 가져오는 길과 소스 관문

> 2부(collect)에서 정한 내용이에요. 원본 소스 목록은 `sources-master.docx` 2·3장(22개 항목).
> 측정: 2026-10-29 16:31 KST, 24시간 범위. 요청 User-Agent는 `my-newsletter-agent/0.1 (RSS reader; personal study)`.

## 다섯 길 비교

위 칸일수록 안전하고, 위 칸을 쓸 수 있으면 아래로 내려가지 않아요.

| 길 | 장점 | 단점 | 이 프로젝트 |
|----|------|------|-------------|
| ① 공식 API | 형식이 안정적, 약관이 분명 | 패션·뷰티 매체는 공개 API가 거의 없어요 | 안 씀 (쓸 수 있는 곳 없음) |
| ② RSS · Atom 피드 | 매체가 "새 글은 여기 적겠다"고 낸 XML이라 허락된 길이고, 시간순이라 "최근 24시간"을 자르기 쉬워요 | 최신 10~50건만 주고, 요약이 짧아요 | **씀** (매체 14곳 · 피드 17개) |
| ③ 공개 데이터셋 | 대량·정제됨 | 실시간이 아니에요 | 안 씀 |
| ④ 집계 서비스 (Google News 등) | 한 번에 많이 | 무엇을 왜 넣었는지 통제를 못 해요 | 안 씀 |
| ⑤ 직접 스크래핑 | 어디든 가능 | 화면이 바뀌면 깨지고, 막히기 쉬워요 | 목록 수집엔 안 쓰고, 고른 기사 본문만 trafilatura로 뽑아요 |

(②와 ⑤ 사이) **사이트맵**: 피드가 없을 때 사이트맵에서 새 글 후보를 찾고 글 페이지 날짜로 다시 거르는 길이에요. ai-newsletter-agent가 Anthropic에 쓴 방법이고, 여기서는 Gentleman's Journal 후보예요(아래 "뺀 곳 재점검").

## 소스 관문 세 개

| 관문 | 질문 | 못 넘으면 |
|------|------|-----------|
| G1 본문 | 원문 주소에서 본문이 600자 넘게 뽑히나? | 제목만 보고 요약을 지어내요 |
| G2 생존 | 최근에도 글이 올라오나? | 매일 0건인데 요청 시간만 써요 |
| G3 접근 | 자동 수집이 막히지 않나? (403·404·410, robots.txt) | 되더라도 안 써요. 우회하지 않아요 |

## 쓰는 소스 (매체 14곳 · 피드 17개)

| 소스 | 피드 | 파트 | 24h 글 | G1 본문 | G2 | 메모 |
|------|------|------|--------|---------|----|------|
| Permanent Style | https://www.permanentstyle.com/feed | menswear | 1 | 통과 (10,423자) | 주 2~3건 | 테일러링 밀도가 높아요. 기사 페이지가 curl엔 403, Python(urllib)엔 200이라 2부에서 `requests`로 다시 확인해요. robots.txt는 GPTBot만 막고 일반 접근 허용 |
| 에스콰이어 코리아 | https://www.esquirekorea.co.kr/rss | mixed | 11 | 통과 (3,225자) | 통과 | 연예·시계·전시 기사가 섞여요 |
| FashionBeans | https://www.fashionbeans.com/feed/ | mixed | 0 | 통과 (6,924자) | 통과 | 하루에 몰아서 올려요(10-27에 17건). 데이팅 글 제외 필요 |
| **GQ 코리아** 🆕 | https://www.gqkorea.co.kr/feed/ | mixed | 10 | 통과 (1,313~2,660자) | 통과 | 전체 피드가 최신 10건(반나절치)만 줘서 아래 카테고리 피드를 같이 읽어요 |
| └ GQ 코리아 Style 🆕 | https://www.gqkorea.co.kr/category/style/feed/ | menswear | 5 | | 통과 | 그루밍 기사도 STYLE에 들어와요 → select가 파트를 다시 정해요 |
| └ GQ 코리아 Fitness 🆕 | https://www.gqkorea.co.kr/category/fitness/feed/ | sports | 0 | | 통과 | |
| └ GQ 코리아 Grooming 🆕 | https://www.gqkorea.co.kr/category/grooming/feed/ | grooming | 0 | | **주의** (10건에 6주) | |
| Runner's World | https://www.runnersworld.com/rss/all.xml/ | sports | 12 | 통과 (6,380자) | 통과 | 여성 전용·경기 결과 제외 필요 |
| Men's Health Fitness | https://www.menshealth.com/rss/fitness.xml/ | sports | 2 | 통과 (6,635자) | 통과 | |
| **Men's Health AU Fitness** 🆕 | https://menshealth.com.au/category/fitness/feed/ | sports | 0 | 미측정 | 주 8건 | 셀럽 운동 기사가 많아요 |
| Outside Online | https://www.outsideonline.com/feed/ | sports | 8 | 통과 (14,445자) | 통과 | 기어 리뷰와 재난 뉴스가 섞여요 |
| SwimSwam Training | https://swimswam.com/training/feed/ | sports | 0 | 통과 (6,051자) | 주 5건 | 전체 피드는 대회 소식뿐이라 훈련 피드로 바꿨어요 |
| Backpacker | https://www.backpacker.com/feed/ | sports | 2 | 통과 (6,721자) | 통과 | 사고 뉴스 제외 |
| 골프매거진코리아 | https://golfmagazinekorea.com/rss | sports | 4 | 통과 (4,171자) | 통과 | 투어 결과가 대부분 |
| Men's Health Grooming | https://www.menshealth.com/rss/grooming.xml/ | grooming | 2 | 통과 (5,630자) | 통과 | |
| Robb Report Grooming | https://robbreport.com/style/grooming/feed/ | grooming | 0 | 통과 (2,635자) | **주의** (한 달 1건 남짓) | 전체 피드는 자동차·부동산뿐이라 그루밍 피드로 바꿨어요 |
| 아모레퍼시픽 스토리 | https://stories.amorepacific.com/feed/ | grooming | 3 | 통과 (1,299~5,515자) | 통과 | 보도자료가 많아요 |

**24시간 합계 60건.** 쓸 만한 후보(수동 확인)는 남성복 3~4 · 스포츠 8 이상 · 화장품 4 정도예요. 화장품이 모자라는 날은 PRD의 배분 규칙 ③으로 다른 파트가 채워요.

## 뺀 곳 재점검 (2026-10-29)

처음에 뺀 10곳을 다시 확인했어요. **막힌 곳을 우회하는 방법은 쓰지 않았어요** (G3 원칙).

| 소스 | 확인한 것 | 결과 | 판단 |
|------|-----------|------|------|
| GQ 코리아 | docx 링크(두산매거진) 대신 gqkorea.co.kr를 확인 → `/feed/`와 카테고리 피드가 있음. robots.txt는 AI 학습 크롤러(GPTBot·ClaudeBot 등)만 막고 일반 접근은 허용 | ✅ **복구** | 4개 피드로 포함 |
| Men's Health AU | `/category/fitness/feed/`에 주 8건. robots.txt 전체 허용 | ✅ **복구** | 스포츠로 포함. 그루밍 카테고리 피드는 없음 |
| Gentleman's Journal | 피드 없음. 사이트맵은 허용(영어 기사 11,924개, `lastmod` 있음) | ⏸ **보류** | 사이트맵 길로 넣을 수 있지만 마지막 갱신이 10-20(9일 전)이라 G2 미달. 일주일 뒤 다시 재요 |
| Racquet Magazine | 피드는 정상, 피드에 전문 없음, 본문 추출 484자, 주 1건 | ⏸ **보류** | G1·G2 미달. 본문 측정은 1건뿐이라 다른 글로 다시 재 볼 가치는 있어요 |
| AskMen | `/feed`에 피드가 있음(10건). 그런데 robots.txt가 ChatGPT-User·GPTBot·OAI-SearchBot·Claude 계열을 명시적으로 막음 | ❌ **제외** | 기술적으론 되지만, 본문을 OpenAI로 요약하는 이 서비스 용도를 사이트가 거부한 것이라 넣지 않아요 |
| MR PORTER | 피드 없음, robots.txt·사이트맵까지 403 | ❌ 제외 | G3 |
| Golf Digest | 피드·robots.txt·사이트맵 403 | ❌ 제외 | G3 |
| 화해 | robots.txt가 랭킹 경로(`/hwahae-rank`)를 금지 | ❌ 제외 | G3 |
| 올리브영 맨즈에딧 | robots.txt 403 | ❌ 제외 | G3 |
| Runner's World 잡지판 · 각종 뉴스레터 가입 페이지 | 구독 판매·가입 페이지 | — | 웹사이트 피드로 이미 대체 |

**정리:** 10곳 중 2곳 복구(GQ 코리아, Men's Health AU), 2곳 보류(Gentleman's Journal, Racquet), 6곳 제외.

## 화장품 파트 보강 후보 (다음 할 일)

- docx 밖의 국내 남성 그루밍 매체를 찾아 같은 관문으로 재 보기
- GQ 코리아 STYLE 피드 안의 그루밍 기사가 select에서 화장품으로 잘 넘어가는지 확인 (0호 화장품 3번이 그 경우예요)
