package com.ktcloud.travelplanner.auth.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertNull

class RedisOneTimeTokenStoreIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var tokenStore: OneTimeTokenStore

	@Test
	fun `Redis atomically consumes a value only once`() {
		tokenStore.put("integration", "one-time-token", "user-value", Duration.ofMinutes(1))

		assertEquals("user-value", tokenStore.consume("integration", "one-time-token"))
		assertNull(tokenStore.consume("integration", "one-time-token"))
	}

	@Test
	fun `Redis removes a value after its TTL`() {
		tokenStore.put("integration", "expiring-token", "user-value", Duration.ofMillis(50))
		Thread.sleep(150)

		assertNull(tokenStore.consume("integration", "expiring-token"))
	}
}
