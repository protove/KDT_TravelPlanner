package com.ktcloud.travelplanner.membership.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelInvitationAction
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelMemberControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val objectMapper: ObjectMapper,
) {
	@Test
	fun `owner accepted members and pending invitations are returned while rejected invitations are excluded`() {
		val owner = saveUser("members-owner")
		val readOnlyUser = saveUser("members-reader")
		val readWriteUser = saveUser("members-writer")
		val pendingUser = saveUser("members-pending")
		val rejectedUser = saveUser("members-rejected")
		val travel = saveTravel(owner)
		saveMember(travel, readOnlyUser, TravelRole.READ_ONLY, TravelInvitationAction.ACCEPT)
		saveMember(travel, readWriteUser, TravelRole.READ_WRITE, TravelInvitationAction.ACCEPT)
		saveMember(travel, pendingUser, TravelRole.READ_ONLY)
		saveMember(travel, rejectedUser, TravelRole.READ_WRITE, TravelInvitationAction.REJECT)

		val result = getMembers(travel, owner)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(4))
				jsonPath("$.data[0].userId", equalTo(owner.id.toString()))
				jsonPath("$.data[0].role", equalTo("OWNER"))
				jsonPath("$.data[0].isOwner", equalTo(true))
			}
			.andReturn()

		val members = objectMapper.readTree(result.response.contentAsString).path("data")
		val actualMemberIds = members.drop(1).map { it.path("userId").asText() }
		val expectedMemberIds =
			listOf(readOnlyUser.id.toString(), readWriteUser.id.toString(), pendingUser.id.toString()).sorted()
		assertEquals(expectedMemberIds, actualMemberIds)
		assertEquals(setOf("READ_ONLY", "READ_WRITE"), members.drop(1).map { it.path("role").asText() }.toSet())
		assertEquals(
			listOf("ACCEPTED", "ACCEPTED", "PENDING"),
			members.drop(1).map { it.path("status").asText() }.sorted(),
		)
	}

	@Test
	fun `owner and accepted roles can query while pending or unrelated user is forbidden`() {
		val owner = saveUser("members-access-owner")
		val readOnlyUser = saveUser("members-access-reader")
		val readWriteUser = saveUser("members-access-writer")
		val pendingUser = saveUser("members-access-pending")
		val outsider = saveUser("members-access-outsider")
		val travel = saveTravel(owner)
		saveMember(travel, readOnlyUser, TravelRole.READ_ONLY, TravelInvitationAction.ACCEPT)
		saveMember(travel, readWriteUser, TravelRole.READ_WRITE, TravelInvitationAction.ACCEPT)
		saveMember(travel, pendingUser, TravelRole.READ_ONLY)

		getMembers(travel, owner).andExpect { status { isOk() } }
		getMembers(travel, readOnlyUser).andExpect { status { isOk() } }
		getMembers(travel, readWriteUser).andExpect { status { isOk() } }
		getMembers(travel, pendingUser)
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
		getMembers(travel, outsider)
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `unauthenticated user cannot query travel members`() {
		val owner = saveUser("members-auth-owner")
		val travel = saveTravel(owner)

		mockMvc.get("/api/v1/travels/${travel.id}/members")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun getMembers(
		travel: Travel,
		requester: User,
	) = mockMvc.get("/api/v1/travels/${travel.id}/members") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "travel-members-${UUID.randomUUID()}",
		).also {
			it.updateOAuthProfile(null, null, "https://example.com/$nickname.png")
			it.completeProfile(nickname, null, null)
		},
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "참여자 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-02"),
		),
	)

	private fun saveMember(
		travel: Travel,
		user: User,
		role: TravelRole,
		action: TravelInvitationAction? = null,
	): TravelMember {
		val member = TravelMember(
			travel = travel,
			user = user,
			role = role,
			invitedAt = Instant.parse("2026-07-01T00:00:00Z"),
		)
		action?.let {
			member.respond(it, Instant.parse("2026-07-02T00:00:00Z"))
		}
		return travelMemberRepository.saveAndFlush(member)
	}
}
