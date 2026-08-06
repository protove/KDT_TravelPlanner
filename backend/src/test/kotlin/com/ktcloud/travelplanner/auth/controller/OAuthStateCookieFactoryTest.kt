package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import org.junit.jupiter.api.Test
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class OAuthStateCookieFactoryTest {
	private val properties = OAuthFlowProperties(
			stateTtl = Duration.ofMinutes(5),
			stateCookieSecure = false,
			exchangeCodeTtl = Duration.ofSeconds(60),
			allowedRedirectOrigins = listOf("http://localhost:3000"),
			frontendRedirectUrl = "http://localhost:3000/auth/callback",
	)
	private val factory = OAuthStateCookieFactory(properties)

	@Test
	fun `creates host-only HttpOnly Lax cookie and expires it with identical attributes`() {
		val created = factory.create("oauth-state")
		val expired = factory.expire()

		assertEquals(OAuthStateCookieFactory.COOKIE_NAME, created.name)
		assertEquals(Duration.ofMinutes(5), created.maxAge)
		assertNull(created.domain)
		assertTrue(created.isHttpOnly)
		assertFalse(created.isSecure)
		assertEquals(OAuthStateCookieFactory.COOKIE_SAME_SITE, created.sameSite)
		assertEquals(OAuthStateCookieFactory.COOKIE_PATH, created.path)
		assertEquals(Duration.ZERO, expired.maxAge)
		assertEquals("", expired.value)
		assertEquals(created.path, expired.path)
		assertEquals(created.sameSite, expired.sameSite)
		assertEquals(created.isHttpOnly, expired.isHttpOnly)
		assertEquals(created.isSecure, expired.isSecure)
	}

	@Test
	fun `creates Secure cookie when production property is enabled`() {
		val secureCookie = OAuthStateCookieFactory(
			properties.copy(stateCookieSecure = true),
		).create("oauth-state")

		assertTrue(secureCookie.isSecure)
	}
}
