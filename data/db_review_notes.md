# db.csv 중복 검토 메모

- 원본 파일: `/Users/choiseoyoon/Downloads/db.csv`
- 전체 데이터 행 수: `286`
- 중복 URL 종류 수: `11`
- 중복 URL에 걸린 전체 행 수: `26`
- 중복 검토 후 유지한 중복 행 수: `8`
- 중복 검토 후 제거한 중복 행 수: `18`
- 최종 정리본 행 수: `268`

## 적용 기준

- 같은 URL이 여러 이슈에 중복 배치된 경우, 제목과 메모가 특정 이슈를 직접 가리키지 않으면 제외 권장.
- 같은 이슈 안에서 frame만 다르게 붙은 경우, 제목과 메모상 더 자연스러운 frame 하나만 유지.
- 너무 일반적인 주간 요약/인터뷰성 기사처럼 특정 이슈 대표 기사로 쓰기 어려운 경우는 제외 권장.

## 추가 수동 검토 권장

- `etoday` 최저임금 기사: 제목상 갈등 구도 성격도 있어 frame을 한 번 더 확인하는 것이 좋음.
- `ifs.or.kr` 지역소멸 기사: 균형 발전/정착 한계 둘 다 가능해 내용 확인 후 최종 frame 고정 권장.
- 현재 CSV의 frame 체계(예: `산업_성장`, `세대_부담`)는 앱 프롬프트 체계와 다르므로, 적재 전 최종 프레임 분류 기준을 팀에서 한 번 더 통일하는 것이 좋음.

## 결과물

- 중복 검토표: `/Users/choiseoyoon/news-bias-analyzer/data/db_duplicate_review.csv`
- 중복 정리본: `/Users/choiseoyoon/news-bias-analyzer/data/db_deduped_reviewed.csv`
