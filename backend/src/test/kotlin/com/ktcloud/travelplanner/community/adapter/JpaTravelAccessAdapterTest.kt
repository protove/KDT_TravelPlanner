package com.ktcloud.travelplanner.community.adapter

import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import java.util.Optional
import java.util.UUID
import kotlin.test.assertFalse
import kotlin.test.assertTrue

// CommunityPostService에 있던 "오너 본인이거나 ACCEPTED 멤버" 판정 로직이 이 어댑터로 옮겨왔으므로
// 그 회귀 커버리지를 여기서 유지한다. (community가 별도 서비스로 분리되면 이 클래스는
// GET /api/v1/travels/{travelId}/read-access 호출 어댑터로 교체된다.)
class JpaTravelAccessAdapterTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val adapter = JpaTravelAccessAdapter(travelRepository, travelMemberRepository)

	private val travelId = UUID.randomUUID()

	@Test
	fun `exists delegates to the travel repository`() {
		`when`(travelRepository.existsById(travelId)).thenReturn(true)

		assertTrue(adapter.exists(travelId))
	}

	@Test
	fun `hasReadAccess is true for the travel owner without a member lookup`() {
		val ownerId = UUID.randomUUID()
		// travelOwnedBy가 내부적으로 mock 스터빙을 하므로, 바깥 when(...).thenReturn(...) 인자 자리에서
		// 바로 호출하면 Mockito가 UnfinishedStubbingException을 던진다 — 먼저 로컬 변수로 확정한다.
		val travel = travelOwnedBy(ownerId)
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.of(travel))

		assertTrue(adapter.hasReadAccess(travelId, ownerId))
		verify(travelMemberRepository, never()).findAcceptedRole(travelId, ownerId)
	}

	@Test
	fun `hasReadAccess is true for an accepted member`() {
		val requesterId = UUID.randomUUID()
		val travel = travelOwnedBy(UUID.randomUUID())
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(travelId, requesterId)).thenReturn(TravelRole.READ_ONLY)

		assertTrue(adapter.hasReadAccess(travelId, requesterId))
	}

	@Test
	fun `hasReadAccess is false when the requester is neither owner nor accepted member`() {
		val requesterId = UUID.randomUUID()
		val travel = travelOwnedBy(UUID.randomUUID())
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(travelId, requesterId)).thenReturn(null)

		assertFalse(adapter.hasReadAccess(travelId, requesterId))
	}

	@Test
	fun `hasReadAccess is false when the travel does not exist`() {
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.empty())

		assertFalse(adapter.hasReadAccess(travelId, UUID.randomUUID()))
	}

	private fun travelOwnedBy(ownerId: UUID): Travel {
		val owner = mock(User::class.java)
		`when`(owner.id).thenReturn(ownerId)
		val travel = mock(Travel::class.java)
		`when`(travel.owner).thenReturn(owner)
		return travel
	}
}
