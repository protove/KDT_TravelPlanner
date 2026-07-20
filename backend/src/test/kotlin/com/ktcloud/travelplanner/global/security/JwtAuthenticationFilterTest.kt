package com.ktcloud.travelplanner.global.security

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.servlet.FilterChain
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse
import org.springframework.security.core.context.SecurityContextHolder
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class JwtAuthenticationFilterTest {
	private val now = Instant.parse("2026-07-15T00:00:00Z")
	private val userId = UUID.fromString("11111111-2222-3333-4444-555555555555")
	private val tokenService = JwtTokenService(
		JwtProperties(
			issuer = "travel-planner-backend",
			accessTokenTtl = Duration.ofMinutes(30),
			secret = "test-jwt-secret-with-at-least-32-bytes",
		),
		Clock.fixed(now, ZoneOffset.UTC),
	)
	private val userRepository = mock(UserRepository::class.java)
	private val filter = JwtAuthenticationFilter(
		tokenService,
		userRepository,
		ApiSecurityErrorHandler(jacksonObjectMapper()),
	)

	@AfterEach
	fun clearSecurityContext() {
		SecurityContextHolder.clearContext()
	}

	@Test
	fun `injects authenticated user principal for valid active user`() {
		val accessToken = tokenService.issueAccessToken(userId).value
		`when`(userRepository.existsById(userId)).thenReturn(true)
		val request = requestWithBearer(accessToken)
		val response = MockHttpServletResponse()
		var invoked = false
		val chain = FilterChain { _, _ -> invoked = true }

		filter.doFilter(request, response, chain)

		assertTrue(invoked)
		assertEquals(
			AuthenticatedUserPrincipal(userId),
			SecurityContextHolder.getContext().authentication.principal,
		)
	}

	@Test
	fun `rejects valid token when user is deleted or absent`() {
		val accessToken = tokenService.issueAccessToken(userId).value
		`when`(userRepository.existsById(userId)).thenReturn(false)
		val response = MockHttpServletResponse()
		var invoked = false

		filter.doFilter(
			requestWithBearer(accessToken),
			response,
			FilterChain { _, _ -> invoked = true },
		)

		assertFalse(invoked)
		assertEquals(401, response.status)
		assertTrue(response.contentAsString.contains("\"code\":\"UNAUTHORIZED\""))
	}

	@Test
	fun `rejects malformed bearer header without exposing token`() {
		val request = MockHttpServletRequest().apply {
			addHeader("Authorization", "Basic sensitive-value")
		}
		val response = MockHttpServletResponse()

		filter.doFilter(request, response, FilterChain { _, _ -> error("must not continue") })

		assertEquals(401, response.status)
		assertFalse(response.contentAsString.contains("sensitive-value"))
	}

	private fun requestWithBearer(token: String): MockHttpServletRequest =
		MockHttpServletRequest().apply {
			addHeader("Authorization", "Bearer $token")
		}
}
