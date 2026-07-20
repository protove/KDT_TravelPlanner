package com.ktcloud.travelplanner.auth.repository

import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.data.redis.core.script.DefaultRedisScript
import org.springframework.stereotype.Component
import org.springframework.stereotype.Repository
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Duration
import java.util.HexFormat
import java.util.UUID

sealed interface RefreshTokenRotationResult {
	data class Rotated(
		val userId: String,
	) : RefreshTokenRotationResult

	data object Reused : RefreshTokenRotationResult

	data object Invalid : RefreshTokenRotationResult
}

interface RefreshTokenStore {
	fun save(token: String, userId: UUID, familyId: String, ttl: Duration)

	fun rotate(token: String, rotatedToken: String): RefreshTokenRotationResult

	fun revokeFamily(token: String)
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
	override fun save(token: String, userId: UUID, familyId: String, ttl: Duration) {
		val tokenHash = tokenHasher.hash(token)
		redisTemplate.execute(
			SAVE_SCRIPT,
			listOf(tokenKey(tokenHash), familyKey(familyId)),
			payload(userId, familyId),
			tokenHash,
			ttl.toMillis().toString(),
		)
	}

	override fun rotate(token: String, rotatedToken: String): RefreshTokenRotationResult {
		val tokenHash = tokenHasher.hash(token)
		val rotatedTokenHash = tokenHasher.hash(rotatedToken)
		val result = redisTemplate.execute(
			ROTATE_SCRIPT,
			listOf(
				tokenKey(tokenHash),
				usedKey(tokenHash),
				tokenKey(rotatedTokenHash),
			),
			tokenHash,
			rotatedTokenHash,
			FAMILY_KEY_PREFIX_WITH_SEPARATOR,
			TOKEN_KEY_PREFIX_WITH_SEPARATOR,
		)
		return when {
			result.startsWith(ROTATION_SUCCESS_PREFIX) ->
				RefreshTokenRotationResult.Rotated(result.removePrefix(ROTATION_SUCCESS_PREFIX))
			result == ROTATION_REUSED -> RefreshTokenRotationResult.Reused
			else -> RefreshTokenRotationResult.Invalid
		}
	}

	override fun revokeFamily(token: String) {
		val tokenHash = tokenHasher.hash(token)
		redisTemplate.execute(
			REVOKE_SCRIPT,
			listOf(tokenKey(tokenHash), usedKey(tokenHash)),
			FAMILY_KEY_PREFIX_WITH_SEPARATOR,
			TOKEN_KEY_PREFIX_WITH_SEPARATOR,
		)
	}

	private fun payload(userId: UUID, familyId: String): String = "$userId$PAYLOAD_SEPARATOR$familyId"

	private fun tokenKey(tokenHash: String): String = "$TOKEN_KEY_PREFIX_WITH_SEPARATOR$tokenHash"

	private fun familyKey(familyId: String): String = "$FAMILY_KEY_PREFIX_WITH_SEPARATOR$familyId"

	private fun usedKey(tokenHash: String): String = "$USED_KEY_PREFIX_WITH_SEPARATOR$tokenHash"

	companion object {
		internal const val KEY_PREFIX = "auth:refresh"
		internal const val TOKEN_KEY_PREFIX = "$KEY_PREFIX:token"
		internal const val FAMILY_KEY_PREFIX = "$KEY_PREFIX:family"
		internal const val USED_KEY_PREFIX = "$KEY_PREFIX:used"
		private const val TOKEN_KEY_PREFIX_WITH_SEPARATOR = "$TOKEN_KEY_PREFIX:"
		private const val FAMILY_KEY_PREFIX_WITH_SEPARATOR = "$FAMILY_KEY_PREFIX:"
		private const val USED_KEY_PREFIX_WITH_SEPARATOR = "$USED_KEY_PREFIX:"
		private const val PAYLOAD_SEPARATOR = "|"
		private const val ROTATION_SUCCESS_PREFIX = "ROTATED|"
		private const val ROTATION_REUSED = "REUSED"
		private const val ROTATION_INVALID = "INVALID"

		private val SAVE_SCRIPT = DefaultRedisScript(
			"""
			redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[3])
			redis.call('SET', KEYS[2], ARGV[2], 'PX', ARGV[3])
			return 'SAVED'
			""".trimIndent(),
			String::class.java,
		)

		private val ROTATE_SCRIPT = DefaultRedisScript(
			"""
			local activePayload = redis.call('GET', KEYS[1])
			if activePayload then
			    local separator = string.find(activePayload, '|', 1, true)
			    if not separator then
			        return 'INVALID'
			    end
			    local userId = string.sub(activePayload, 1, separator - 1)
			    local familyId = string.sub(activePayload, separator + 1)
			    local familyKey = ARGV[3] .. familyId
			    local currentTokenHash = redis.call('GET', familyKey)
			    if currentTokenHash ~= ARGV[1] then
			        return 'INVALID'
			    end
			    local remainingTtl = redis.call('PTTL', familyKey)
			    if remainingTtl <= 0 then
			        return 'INVALID'
			    end
			    redis.call('DEL', KEYS[1])
			    redis.call('SET', KEYS[2], familyId, 'PX', remainingTtl)
			    redis.call('SET', KEYS[3], activePayload, 'PX', remainingTtl)
			    redis.call('SET', familyKey, ARGV[2], 'PX', remainingTtl)
			    return 'ROTATED|' .. userId
			end

			local reusedFamilyId = redis.call('GET', KEYS[2])
			if not reusedFamilyId then
			    return 'INVALID'
			end
			local reusedFamilyKey = ARGV[3] .. reusedFamilyId
			local activeTokenHash = redis.call('GET', reusedFamilyKey)
			if activeTokenHash then
			    redis.call('DEL', ARGV[4] .. activeTokenHash)
			end
			redis.call('DEL', reusedFamilyKey)
			return 'REUSED'
			""".trimIndent(),
			String::class.java,
		)

		private val REVOKE_SCRIPT = DefaultRedisScript(
			"""
			local activePayload = redis.call('GET', KEYS[1])
			local familyId = nil
			if activePayload then
			    local separator = string.find(activePayload, '|', 1, true)
			    if separator then
			        familyId = string.sub(activePayload, separator + 1)
			    end
			else
			    familyId = redis.call('GET', KEYS[2])
			end
			if not familyId then
			    return 'NOT_FOUND'
			end
			local familyKey = ARGV[1] .. familyId
			local activeTokenHash = redis.call('GET', familyKey)
			if activeTokenHash then
			    redis.call('DEL', ARGV[2] .. activeTokenHash)
			end
			redis.call('DEL', KEYS[1])
			redis.call('DEL', familyKey)
			return 'REVOKED'
			""".trimIndent(),
			String::class.java,
		)
	}
}
