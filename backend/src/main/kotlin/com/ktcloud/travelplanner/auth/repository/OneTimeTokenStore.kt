package com.ktcloud.travelplanner.auth.repository

import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.stereotype.Repository
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Duration
import java.util.HexFormat

interface OneTimeTokenStore {
	fun put(namespace: String, token: String, value: String, ttl: Duration)

	fun consume(namespace: String, token: String): String?
}

@Repository
class RedisOneTimeTokenStore(
	private val redisTemplate: StringRedisTemplate,
) : OneTimeTokenStore {
	override fun put(namespace: String, token: String, value: String, ttl: Duration) {
		redisTemplate.opsForValue().set(key(namespace, token), value, ttl)
	}

	override fun consume(namespace: String, token: String): String? =
		redisTemplate.opsForValue().getAndDelete(key(namespace, token))

	private fun key(namespace: String, token: String): String {
		val digest = MessageDigest.getInstance(SHA_256)
			.digest(token.toByteArray(StandardCharsets.UTF_8))
		return "$KEY_PREFIX:$namespace:${HexFormat.of().formatHex(digest)}"
	}

	companion object {
		private const val KEY_PREFIX = "auth:one-time"
		private const val SHA_256 = "SHA-256"
	}
}
