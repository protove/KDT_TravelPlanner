package com.ktcloud.travelplanner.place.repository

import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.place.port.PlaceLocationCache
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.stereotype.Repository
import java.math.BigDecimal
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Duration
import java.util.HexFormat

@Repository
class RedisPlaceLocationCache(
	private val redisTemplate: StringRedisTemplate,
) : PlaceLocationCache {
	override fun findLocation(googlePlaceId: String): PlaceLocation? {
		val key = key(googlePlaceId)
		val value = redisTemplate.opsForValue().get(key) ?: return null
		return parseLocation(value) ?: run {
			redisTemplate.delete(key)
			null
		}
	}

	override fun saveLocation(googlePlaceId: String, location: PlaceLocation) {
		val value = "${location.latitude.toPlainString()},${location.longitude.toPlainString()}"
		redisTemplate.opsForValue().set(key(googlePlaceId), value, LOCATION_CACHE_TTL)
	}

	private fun parseLocation(value: String): PlaceLocation? {
		return try {
			val coordinates = value.split(COORDINATE_SEPARATOR, limit = 2)
			if (coordinates.size != 2) return null
			PlaceLocation(BigDecimal(coordinates[0]), BigDecimal(coordinates[1]))
		} catch (_: IllegalArgumentException) {
			null
		}
	}

	private fun key(googlePlaceId: String): String {
		val digest = MessageDigest.getInstance(HASH_ALGORITHM)
			.digest(googlePlaceId.toByteArray(StandardCharsets.UTF_8))
		return KEY_PREFIX + HexFormat.of().formatHex(digest)
	}

	companion object {
		internal const val KEY_PREFIX = "google:places:location:"
		internal val LOCATION_CACHE_TTL: Duration = Duration.ofDays(29)
		private const val HASH_ALGORITHM = "SHA-256"
		private const val COORDINATE_SEPARATOR = ","
	}
}
