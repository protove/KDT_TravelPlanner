package com.ktcloud.travelplanner.travel.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional
import java.sql.Timestamp
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelListControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val countryRepository: CountryRepository,
	@Autowired private val cityRepository: CityRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `lists only owned and accepted travels ordered by update time with keyword and pages`() {
		val requester = saveUser("list-requester")
		val otherOwner = saveUser("list-other-owner")
		val owned = saveTravel(requester, "Tokyo Owner", OWNED_ID)
		val accepted = saveTravel(otherOwner, "Tokyo Shared", ACCEPTED_ID)
		val pending = saveTravel(otherOwner, "Tokyo Pending", PENDING_ID)
		val outsider = saveTravel(otherOwner, "Tokyo Outsider", OUTSIDER_ID)
		val deleted = saveTravel(requester, "Tokyo Deleted", DELETED_ID)

		acceptMembership(accepted, requester, TravelRole.READ_WRITE)
		travelMemberRepository.saveAndFlush(
			TravelMember(
				travel = pending,
				user = requester,
				role = TravelRole.READ_ONLY,
				invitedAt = Instant.parse("2026-01-01T00:00:00Z"),
			),
		)
		updateTravel(owned.id, "2026-01-01T00:00:00Z")
		updateTravel(accepted.id, "2026-01-03T00:00:00Z")
		updateTravel(pending.id, "2026-01-05T00:00:00Z")
		updateTravel(outsider.id, "2026-01-06T00:00:00Z")
		updateTravel(deleted.id, "2026-01-07T00:00:00Z", deleted = true)
		entityManager.clear()

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "tokyo")
			param("page", "0")
			param("size", "1")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content[0].travelId", equalTo(ACCEPTED_ID.toString()))
				jsonPath("$.data.content[0].permission", equalTo("READ_WRITE"))
				jsonPath("$.data.page", equalTo(0))
				jsonPath("$.data.size", equalTo(1))
				jsonPath("$.data.totalElements", equalTo(2))
				jsonPath("$.data.totalPages", equalTo(2))
				jsonPath("$.data.isFirst", equalTo(true))
				jsonPath("$.data.isLast", equalTo(false))
			}

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "Tokyo")
			param("page", "1")
			param("size", "1")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content[0].travelId", equalTo(OWNED_ID.toString()))
				jsonPath("$.data.content[0].permission", equalTo("OWNER"))
				jsonPath("$.data.isLast", equalTo(true))
			}
	}

	@Test
	fun `keyword search also matches description, country name, and city name (not just title)`() {
		val requester = saveUser("scope-requester")
		val country = countryRepository.findByIdAndIsActiveTrue(SEED_COUNTRY_ID).orElseThrow()
		val city = cityRepository.findByIdAndIsActiveTrue(SEED_CITY_ID).orElseThrow()

		val byDescription = saveTravel(requester, "무제 일정 1", UUID.randomUUID())
		byDescription.updateBasicInfo(
			title = byDescription.title,
			startDate = byDescription.startDate,
			endDate = byDescription.endDate,
			country = null,
			city = null,
			companionType = null,
			participantCount = null,
			comment = "친구들이랑 벚꽃 보러 가는 여행",
		)
		val byCountryAndCity = saveTravel(requester, "무제 일정 2", UUID.randomUUID())
		byCountryAndCity.updateBasicInfo(
			title = byCountryAndCity.title,
			startDate = byCountryAndCity.startDate,
			endDate = byCountryAndCity.endDate,
			country = country,
			city = city,
			companionType = null,
			participantCount = null,
			comment = null,
		)
		saveTravel(requester, "전혀 무관한 일정", UUID.randomUUID())
		travelRepository.saveAllAndFlush(listOf(byDescription, byCountryAndCity))

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "벚꽃")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].travelId", equalTo(byDescription.id.toString()))
		}

		// 국가명(한글, "일본")으로도 매칭된다.
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", country.nameKo)
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].travelId", equalTo(byCountryAndCity.id.toString()))
		}

		// 도시명(영문)으로도, 대소문자 무시하고 매칭된다.
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", city.nameEn.lowercase())
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].travelId", equalTo(byCountryAndCity.id.toString()))
		}
	}

	@Test
	fun `searchScope narrows keyword matching to the requested field`() {
		val requester = saveUser("scope-narrow-requester")
		val country = countryRepository.findByIdAndIsActiveTrue(SEED_COUNTRY_ID).orElseThrow()
		val city = cityRepository.findByIdAndIsActiveTrue(SEED_CITY_ID).orElseThrow()

		val byTitle = saveTravel(requester, "벚꽃 여행", UUID.randomUUID())
		val byDescription = saveTravel(requester, "무제 일정", UUID.randomUUID())
		byDescription.updateBasicInfo(
			title = byDescription.title,
			startDate = byDescription.startDate,
			endDate = byDescription.endDate,
			country = null,
			city = null,
			companionType = null,
			participantCount = null,
			comment = "벚꽃 보러 가는 여행",
		)
		val byDestination = saveTravel(requester, "무제 일정 2", UUID.randomUUID())
		byDestination.updateBasicInfo(
			title = byDestination.title,
			startDate = byDestination.startDate,
			endDate = byDestination.endDate,
			country = country,
			city = city,
			companionType = null,
			participantCount = null,
			comment = null,
		)
		travelRepository.saveAllAndFlush(listOf(byDescription, byDestination))

		// searchScope=TITLE이면 제목에만 매칭되는 것을 찾고, 설명에만 있는 키워드는 걸러진다.
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "벚꽃")
			param("searchScope", "TITLE")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].travelId", equalTo(byTitle.id.toString()))
		}

		// searchScope=DESTINATION이면 국가/도시명에만 매칭되고, 제목/설명은 걸러진다.
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", country.nameKo)
			param("searchScope", "DESTINATION")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].travelId", equalTo(byDestination.id.toString()))
		}

		// 알 수 없는 searchScope 값은 ALL로 취급돼 세 필드 모두 훑는다.
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "벚꽃")
			param("searchScope", "invalid-scope")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(2))
		}
	}

	@Test
	fun `rejects unauthenticated and invalid pagination requests`() {
		mockMvc.get("/api/v1/travels")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}

		val requester = saveUser("invalid-page-requester")
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("page", "-1")
			param("size", "101")
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
	}

	@Test
	fun `lists owned travel when keyword parameter is omitted`() {
		val requester = saveUser("no-keyword-requester")
		val travel = saveTravel(requester, "검색어 없는 목록", UUID.randomUUID())

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content[0].travelId", equalTo(travel.id.toString()))
				jsonPath("$.data.totalElements", equalTo(1))
			}
	}

	private fun acceptMembership(
		travel: Travel,
		user: User,
		role: TravelRole,
	) {
		val member = travelMemberRepository.saveAndFlush(
			TravelMember(
				travel = travel,
				user = user,
				role = role,
				invitedAt = Instant.parse("2026-01-01T00:00:00Z"),
			),
		)
		jdbcTemplate.update(
			"UPDATE planner_members SET status = 'ACCEPTED', responded_at = ? WHERE id = ?",
			Timestamp.from(Instant.parse("2026-01-02T00:00:00Z")),
			member.id,
		)
	}

	private fun updateTravel(
		travelId: UUID,
		updatedAt: String,
		deleted: Boolean = false,
	) {
		jdbcTemplate.update(
			"UPDATE planners_table SET updated_at = ?, deleted_at = ? WHERE id = ?",
			Timestamp.from(Instant.parse(updatedAt)),
			if (deleted) Timestamp.from(Instant.parse(updatedAt)) else null,
			travelId,
		)
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "list-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(
		owner: User,
		title: String,
		travelId: UUID,
	): Travel = travelRepository.saveAndFlush(
		Travel(
			id = travelId,
			owner = owner,
			title = title,
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-04"),
		),
	)

	companion object {
		// V3__seed_location_catalog.sql — country_table id=1(일본/Japan), city_table id=10(도쿄/Tokyo, country_id=1).
		private val SEED_COUNTRY_ID: Short = 1
		private val SEED_CITY_ID: Long = 10
		private val OWNED_ID = UUID.fromString("00000000-0000-0000-0000-000000000180")
		private val ACCEPTED_ID = UUID.fromString("00000000-0000-0000-0000-000000000181")
		private val PENDING_ID = UUID.fromString("00000000-0000-0000-0000-000000000182")
		private val OUTSIDER_ID = UUID.fromString("00000000-0000-0000-0000-000000000183")
		private val DELETED_ID = UUID.fromString("00000000-0000-0000-0000-000000000184")
	}
}
