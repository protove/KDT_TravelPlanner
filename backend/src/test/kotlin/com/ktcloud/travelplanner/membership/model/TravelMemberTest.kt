package com.ktcloud.travelplanner.membership.model

import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Instant
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertNull

class TravelMemberTest {
	@Test
	fun `pending invitation can be accepted once`() {
		val member = invitation()
		val respondedAt = Instant.parse("2026-01-02T00:00:00Z")

		member.respond(TravelInvitationAction.ACCEPT, respondedAt)

		assertEquals(InvitationStatus.ACCEPTED, member.status)
		assertEquals(respondedAt, member.respondedAt)
		assertThrows<IllegalStateException> {
			member.respond(TravelInvitationAction.REJECT, respondedAt.plusSeconds(1))
		}
	}

	@Test
	fun `pending invitation can be rejected`() {
		val member = invitation()
		val respondedAt = Instant.parse("2026-01-02T00:00:00Z")

		member.respond(TravelInvitationAction.REJECT, respondedAt)

		assertEquals(InvitationStatus.REJECTED, member.status)
		assertEquals(respondedAt, member.respondedAt)
	}

	@Test
	fun `new invitation starts pending with requested role and invite time`() {
		val member = invitation()

		assertEquals("membership-owner", member.travel.owner.providerUserId)
		assertEquals("membership-invitee", member.user.providerUserId)
		assertEquals(TravelRole.READ_WRITE, member.role)
		assertEquals(InvitationStatus.PENDING, member.status)
		assertEquals(TestFixtures.FIXED_INSTANT, member.invitedAt)
		assertNull(member.respondedAt)
	}

	private fun invitation(): TravelMember {
		val owner = User(OAuthProvider.GOOGLE, "membership-owner")
		val invitee = User(OAuthProvider.NAVER, "membership-invitee")
		val travel = Travel(
			owner = owner,
			title = "초대 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-02"),
		)
		return TravelMember(
			travel = travel,
			user = invitee,
			role = TravelRole.READ_WRITE,
			invitedAt = TestFixtures.FIXED_INSTANT,
		)
	}
}
