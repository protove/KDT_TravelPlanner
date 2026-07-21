package com.ktcloud.travelplanner.travel.model

import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.location.model.Country
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertSame
import kotlin.test.assertTrue

class TravelTest {
        private val owner = User(OAuthProvider.GOOGLE, "travel-owner")

        @Test
        fun `requires title and valid date range`() {
                assertThrows<IllegalArgumentException> {
                        Travel(
                                owner = owner,
                                title = " ",
                                startDate = LocalDate.parse("2026-08-01"),
                                endDate = LocalDate.parse("2026-08-04"),
                        )
                }
                assertThrows<IllegalArgumentException> {
                        Travel(
                                owner = owner,
                                title = "도쿄 여행",
                                startDate = LocalDate.parse("2026-08-04"),
                                endDate = LocalDate.parse("2026-08-01"),
                        )
                }
        }

        @Test
        fun `keeps authenticated owner and calculates inclusive travel days`() {
                val travel = Travel(
                        owner = owner,
                        title = "도쿄 여행",
                        startDate = LocalDate.parse("2026-08-01"),
                        endDate = LocalDate.parse("2026-08-04"),
                )

                assertSame(owner, travel.owner)
                assertEquals(4, travel.travelDays)
        }

        @Test
        fun `soft deletes once with supplied UTC time`() {
                val travel = Travel(
                        owner = owner,
                        title = "삭제 여행",
                        startDate = LocalDate.parse("2026-08-01"),
                        endDate = LocalDate.parse("2026-08-04"),
                )

                travel.softDelete(TestFixtures.FIXED_INSTANT)

                assertTrue(travel.isDeleted)
                assertEquals(TestFixtures.FIXED_INSTANT, travel.deletedAt)
                assertThrows<IllegalArgumentException> { travel.softDelete(TestFixtures.FIXED_INSTANT) }
        }

        @Test
        fun `updates basic info only when dates participant count and location are valid`() {
                val travel = Travel(
                        owner = owner,
                        title = "수정 전 여행",
                        startDate = LocalDate.parse("2026-08-01"),
                        endDate = LocalDate.parse("2026-08-04"),
                )
                val country = Country(1, "JP", "일본", "Japan")
                val city = City(10, country, "도쿄", "Tokyo")

                travel.updateBasicInfo(
                        title = "수정 후 여행",
                        startDate = LocalDate.parse("2026-08-02"),
                        endDate = LocalDate.parse("2026-08-05"),
                        country = country,
                        city = city,
                        companionType = CompanionType.FRIEND,
                        participantCount = 3,
                        comment = "맛집 중심",
                        purposes = setOf(TravelPurpose.SIGHTSEEING, TravelPurpose.FOOD),
                )

                assertEquals("수정 후 여행", travel.title)
                assertSame(city, travel.city)
                assertEquals(3, travel.participantCount?.toInt())
                assertEquals(setOf(TravelPurpose.SIGHTSEEING, TravelPurpose.FOOD), travel.purposes)

                val otherCountry = Country(2, "KR", "대한민국", "South Korea")
                assertThrows<IllegalArgumentException> {
                        travel.updateBasicInfo(
                                travel.title,
                                travel.startDate,
                                travel.endDate,
                                otherCountry,
                                city,
                                travel.companionType,
                                travel.participantCount,
                                travel.comment,
                                travel.purposes,
                        )
                }
        }
}
