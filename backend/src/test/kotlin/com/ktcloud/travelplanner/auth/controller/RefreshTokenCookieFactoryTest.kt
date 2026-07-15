package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import org.junit.jupiter.api.Test
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RefreshTokenCookieFactoryTest {
	private val factory = RefreshTokenCookieFactory(
		RefreshTokenProperties(
			ttl = Duration.ofDays(30),
			cookieSecure = false,
			cookieSameSite = "Lax",
		),
	)

	@Test
	fun `creates and expires Cookie with identical security attributes`() {
		val created = factory.create("refresh-token")
		val expired = factory.expire()

		assertEquals(RefreshTokenCookieFactory.COOKIE_NAME, created.name)
		assertEquals(Duration.ofDays(30), created.maxAge)
		assertEquals(Duration.ZERO, expired.maxAge)
		assertEquals("", expired.value)
		assertEquals(created.path, expired.path)
		assertEquals(created.sameSite, expired.sameSite)
		assertEquals(created.isHttpOnly, expired.isHttpOnly)
		assertEquals(created.isSecure, expired.isSecure)
		assertEquals(RefreshTokenCookieFactory.COOKIE_PATH, expired.path)
		assertEquals("Lax", expired.sameSite)
		assertTrue(expired.isHttpOnly)
		assertFalse(expired.isSecure)
	}
}
