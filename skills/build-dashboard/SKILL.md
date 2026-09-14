---
name: build-dashboard
description: 저장된 연구 결과의 화면·객체 지도 요청을 처리한다. D3에서는 고정 snapshot과 인용 보고서까지만 제공하며 대시보드·방향 그래프 구현은 D5다.
---

# 저장 결과 표시 요청

[실행 계약](../../plugin/workflows/RUNTIME_GUIDE.md)을 읽고 실제 snapshot과 report를 확인한다. D3에는 interactive dashboard/객체 지도 구현이 없다. 사용자가 요청한 현재 결과는 저장된 report를 export하여 볼 수 있게 한다. 존재하지 않는 사이트·화면·지도 링크를 만들지 않는다.

D5의 화면은 같은 검증 snapshot의 읽기 전용 projection이어야 한다. 기술 의존·관측된 지연 전파·조건부 전파를 구별하고 그래프 연결 수를 점수에 더하지 않는다. 레이아웃 방향을 병목 순위로 설명하지 않는다. 화면 요청만으로 새 평가나 baseline 승격을 수행하지 않는다.
