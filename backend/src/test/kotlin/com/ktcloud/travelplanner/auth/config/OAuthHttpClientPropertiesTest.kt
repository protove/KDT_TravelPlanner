package com.ktcloud.travelplanner.auth.config

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Duration

class OAuthHttpClientPropertiesTest {
	@Test
	fun `rejects zero or negative HTTP timeouts`() {
		assertThrows<IllegalArgumentException> {
			OAuthHttpClientProperties(connectTimeout = Duration.ZERO)
		}
		assertThrows<IllegalArgumentException> {
			OAuthHttpClientProperties(readTimeout = Duration.ofMillis(-1))
		}
	}
}
