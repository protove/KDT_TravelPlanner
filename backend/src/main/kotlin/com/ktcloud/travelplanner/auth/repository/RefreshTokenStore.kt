package com.ktcloud.travelplanner.auth.repository

import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.stereotype.Component
import org.springframework.stereotype.Repository
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Duration
import java.util.HexFormat
import java.util.UUID

interface RefreshTokenStore {
	fun save(token: String, userId: UUID, ttl: Duration)

	fun findUserId(token: String): String?
}

@Component
class RefreshTokenHasher {
	fun hash(token: String): String {
		val digest = MessageDigest.getInstance(SHA_256)
			.digest(token.toByteArray(StandardCharsets.UTF_8))
		return HexFormat.of().formatHex(digest)
	}

	companion object {
		private const val SHA_256 = "SHA-256"
	}
}

@Repository
class RedisRefreshTokenStore(
	private val redisTemplate: StringRedisTemplate,
	private val tokenHasher: RefreshTokenHasher,
) : RefreshTokenStore {
	override fun save(token: String, userId: UUID, ttl: Duration) {
		redisTemplate.opsForValue().set(key(token), userId.toString(), ttl)
	}

	override fun findUserId(token: String): String? = redisTemplate.opsForValue().get(key(token))

	private fun key(token: String): String = "$KEY_PREFIX:${tokenHasher.hash(token)}"

	companion object {
		internal const val KEY_PREFIX = "auth:refresh"
	}
}
