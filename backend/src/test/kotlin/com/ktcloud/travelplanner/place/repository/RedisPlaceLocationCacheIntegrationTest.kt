package com.ktcloud.travelplanner.place.repository

import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.data.redis.core.StringRedisTemplate
import java.math.BigDecimal
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Duration
import java.util.HexFormat
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RedisPlaceLocationCacheIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var cache: RedisPlaceLocationCache

	@Autowired
	private lateinit var redisTemplate: StringRedisTemplate

	@Test
	fun `stores coordinates under hashed Place ID with twenty nine day TTL`() {
		val googlePlaceId = "redis-place-${UUID.randomUUID()}"
		val key = key(googlePlaceId)
		val location = PlaceLocation(BigDecimal("35.658581"), BigDecimal("139.745433"))
		try {
			cache.saveLocation(googlePlaceId, location)

			assertEquals(location, cache.findLocation(googlePlaceId))
			assertFalse(key.contains(googlePlaceId))
			val ttlSeconds = redisTemplate.getExpire(key)
			assertTrue(ttlSeconds in Duration.ofDays(28).seconds..RedisPlaceLocationCache.LOCATION_CACHE_TTL.seconds)
		} finally {
			redisTemplate.delete(key)
		}
	}

	@Test
	fun `removes a malformed cached coordinate value`() {
		val googlePlaceId = "malformed-place-${UUID.randomUUID()}"
		val key = key(googlePlaceId)
		redisTemplate.opsForValue().set(key, "invalid-location", Duration.ofMinutes(1))

		assertNull(cache.findLocation(googlePlaceId))
		assertEquals(false, redisTemplate.hasKey(key))
	}

	private fun key(googlePlaceId: String): String {
		val digest = MessageDigest.getInstance("SHA-256")
			.digest(googlePlaceId.toByteArray(StandardCharsets.UTF_8))
		return RedisPlaceLocationCache.KEY_PREFIX + HexFormat.of().formatHex(digest)
	}
}
