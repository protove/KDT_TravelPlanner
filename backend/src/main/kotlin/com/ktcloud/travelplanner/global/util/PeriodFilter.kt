package com.ktcloud.travelplanner.global.util

import java.time.LocalDate
import java.time.ZoneOffset

// 검색 화면의 "기간" 필터(달력 날짜, LocalDate)를 createdAt(timestamptz) 비교용 경계값으로 바꾼다.
// UTC 자정 기준 [start, end+1일) 반open 구간 — endDate 그날 안에 생성된 것까지 포함하면서도
// 정밀도 절삭 문제(23:59:59.999...) 없이 다음날 00:00 미만으로 명확히 자른다.
// 문자열(ISO-8601)로 반환하는 이유 — 네이티브/JPQL 쿼리 모두 "CAST(:param AS timestamptz) IS NULL
// OR ..." 형태로 기간 없음(null)을 처리하는데, Instant? 타입을 그대로 바인딩하면 null일 때
// Hibernate가 타입을 못 정해 postgres가 "cannot cast type bytea to ..."로 거부한다(keyword를
// CAST(:keyword AS string)으로 다루는 것과 동일한 이유 — String은 null이어도 타입이 명확하다).
fun LocalDate.toStartOfDayInstant(): String = atStartOfDay(ZoneOffset.UTC).toInstant().toString()

fun LocalDate.toExclusiveEndOfDayInstant(): String = plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant().toString()
