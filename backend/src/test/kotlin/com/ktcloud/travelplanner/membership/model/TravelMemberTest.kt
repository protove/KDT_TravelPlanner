package com.ktcloud.travelplanner.membership.model

import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertSame

class TravelMemberTest {
	@Test
	fun `new invitation starts pending with requested role and invite time`() {
		val owner = User(OAuthProvider.GOOGLE, "membership-owner")
		val invitee = User(OAuthProvider.NAVER, "membership-invitee")
		val travel = Travel(
			owner = owner,
			title = "초대 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-02"),
		)

		val member = TravelMember(
			travel = travel,
			user = invitee,
			role = TravelRole.READ_WRITE,
			invitedAt = TestFixtures.FIXED_INSTANT,
		)

		assertSame(travel, member.travel)
		assertSame(invitee, member.user)
		assertEquals(TravelRole.READ_WRITE, member.role)
		assertEquals(InvitationStatus.PENDING, member.status)
		assertEquals(TestFixtures.FIXED_INSTANT, member.invitedAt)
		assertNull(member.respondedAt)
	}
}
