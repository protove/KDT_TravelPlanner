package com.ktcloud.travelplanner.travel.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.CompanionType
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.nullValue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.patch
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertNull

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelUpdateControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val timelineItemRepository: TimelineItemRepository,
	@Autowired private val countryRepository: CountryRepository,
	@Autowired private val cityRepository: CityRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner updates fields clears nullable values and increments jpa version`() {
		val owner = saveUser("update-owner")
		val travel = saveTravel(owner)
		val country = countryRepository.findActive().first()
		val city = cityRepository.findActiveByCountryId(country.id).first()

		patchTravel(
			travel,
			owner,
			"""
			{
			  "title": "수정 후 여행",
			  "countryId": ${country.id},
			  "cityId": ${city.id},
			  "companionType": "FRIEND",
			  "companionCount": 3,
			  "comment": "맛집 중심",
			  "version": 0
			}
			""".trimIndent(),
		)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.title", equalTo("수정 후 여행"))
				jsonPath("$.data.countryId", equalTo(country.id.toInt()))
				jsonPath("$.data.cityId", equalTo(city.id.toInt()))
				jsonPath("$.data.participantCount", equalTo(3))
				jsonPath("$.data.version", equalTo(1))
			}

		entityManager.clear()
		val updated = travelRepository.findById(travel.id).orElseThrow()
		assertEquals(CompanionType.FRIEND, updated.companionType)
		assertEquals(1, updated.version)

		patchTravel(
			travel,
			owner,
			"""
			{
			  "countryId": null,
			  "cityId": null,
			  "companionType": null,
			  "companionCount": null,
			  "comment": null,
			  "version": 1
			}
			""".trimIndent(),
		)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.countryId", nullValue())
				jsonPath("$.data.cityId", nullValue())
				jsonPath("$.data.participantCount", nullValue())
				jsonPath("$.data.version", equalTo(2))
			}

		entityManager.clear()
		val cleared = travelRepository.findById(travel.id).orElseThrow()
		assertNull(cleared.country)
		assertNull(cleared.city)
		assertNull(cleared.comment)
		assertEquals(2, cleared.version)
	}

	@Test
	fun `accepted read write can update while read only is forbidden`() {
		val owner = saveUser("update-access-owner")
		val readWrite = saveUser("update-read-write")
		val readOnly = saveUser("update-read-only")
		val travel = saveTravel(owner)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		patchTravel(travel, readWrite, """{"comment":"공동 수정","version":0}""")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.permission", equalTo("READ_WRITE"))
				jsonPath("$.data.version", equalTo(1))
			}
		patchTravel(travel, readOnly, """{"comment":"거부","version":1}""")
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `stale version and date change conflicting with timeline return conflict`() {
		val owner = saveUser("update-conflict-owner")
		val travel = saveTravel(owner)
		timelineItemRepository.saveAndFlush(
			TimelineItem(
				travel = travel,
				dayNumber = 3,
				visitDate = LocalDate.parse("2026-08-03"),
				category = TimelineCategory.OTHER,
				name = "마지막 일정",
				visitOrder = 1,
			),
		)

		patchTravel(travel, owner, """{"title":"첫 수정","version":0}""")
			.andExpect { status { isOk() } }
		patchTravel(travel, owner, """{"title":"stale 수정","version":0}""")
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
		patchTravel(travel, owner, """{"endDate":"2026-08-02","version":1}""")
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
	}

	@Test
	fun `required field null and invalid companion count return validation errors`() {
		val owner = saveUser("update-validation-owner")
		val travel = saveTravel(owner)

		patchTravel(travel, owner, """{"title":null,"version":0}""")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("title"))
			}
		patchTravel(travel, owner, """{"companionCount":0,"version":0}""")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("companionCount"))
			}
	}

	private fun patchTravel(
		travel: Travel,
		requester: User,
		body: String,
	) = mockMvc.patch("/api/v1/travels/${travel.id}") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		contentType = MediaType.APPLICATION_JSON
		content = body
	}

	private fun acceptMember(
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
		jdbcTemplate.update("UPDATE planner_members SET status = 'ACCEPTED' WHERE id = ?", member.id)
		entityManager.clear()
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "update-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "수정 전 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
