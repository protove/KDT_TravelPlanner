package com.ktcloud.travelplanner.global.security

import com.nimbusds.jose.JWSAlgorithm
import com.nimbusds.jose.jwk.JWKSet
import com.nimbusds.jose.jwk.OctetSequenceKey
import com.nimbusds.jose.jwk.source.ImmutableJWKSet
import com.nimbusds.jose.proc.SecurityContext
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator
import org.springframework.security.oauth2.jwt.JwtClaimsSet
import org.springframework.security.oauth2.jwt.JwtEncoderParameters
import org.springframework.security.oauth2.jwt.JwtException
import org.springframework.security.oauth2.jwt.JwtIssuerValidator
import org.springframework.security.oauth2.jwt.JwtTimestampValidator
import org.springframework.security.oauth2.jwt.JwsHeader
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder
import org.springframework.security.oauth2.jose.jws.MacAlgorithm
import org.springframework.stereotype.Service
import java.nio.charset.StandardCharsets
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.util.UUID
import javax.crypto.spec.SecretKeySpec

data class IssuedAccessToken(
	val value: String,
	val expiresAt: Instant,
)

class InvalidAccessTokenException(
	cause: Throwable? = null,
) : RuntimeException("Access token is invalid.", cause)

@Service
class JwtTokenService(
	private val properties: JwtProperties,
	@Qualifier("utcClock") private val clock: Clock,
) {
	private val secretKey = SecretKeySpec(
		properties.secret.toByteArray(StandardCharsets.UTF_8),
		HMAC_SHA_256,
	)
	private val encoder = NimbusJwtEncoder(
		ImmutableJWKSet<SecurityContext>(
			JWKSet(
				OctetSequenceKey.Builder(secretKey)
					.algorithm(JWSAlgorithm.HS256)
					.build(),
			),
		),
	)
	private val decoder = NimbusJwtDecoder.withSecretKey(secretKey)
		.macAlgorithm(MacAlgorithm.HS256)
		.build()
		.apply {
			val timestampValidator = JwtTimestampValidator(Duration.ZERO).apply {
				setClock(clock)
			}
			setJwtValidator(
				DelegatingOAuth2TokenValidator(
					timestampValidator,
					JwtIssuerValidator(properties.issuer),
				),
			)
		}

	fun issueAccessToken(userId: UUID): IssuedAccessToken {
		val issuedAt = Instant.now(clock)
		val expiresAt = issuedAt.plus(properties.accessTokenTtl)
		val claims = JwtClaimsSet.builder()
			.issuer(properties.issuer)
			.issuedAt(issuedAt)
			.expiresAt(expiresAt)
			.subject(userId.toString())
			.claim(TOKEN_TYPE_CLAIM, ACCESS_TOKEN_TYPE)
			.build()
		val headers = JwsHeader.with(MacAlgorithm.HS256)
			.type("JWT")
			.build()

		return IssuedAccessToken(
			value = encoder.encode(JwtEncoderParameters.from(headers, claims)).tokenValue,
			expiresAt = expiresAt,
		)
	}

	fun parseUserId(token: String): UUID = try {
		val jwt = decoder.decode(token)
		if (jwt.getClaimAsString(TOKEN_TYPE_CLAIM) != ACCESS_TOKEN_TYPE) {
			throw InvalidAccessTokenException()
		}
		UUID.fromString(jwt.subject)
	} catch (exception: InvalidAccessTokenException) {
		throw exception
	} catch (exception: JwtException) {
		throw InvalidAccessTokenException(exception)
	} catch (exception: IllegalArgumentException) {
		throw InvalidAccessTokenException(exception)
	}

	companion object {
		private const val HMAC_SHA_256 = "HmacSHA256"
		private const val TOKEN_TYPE_CLAIM = "token_type"
		private const val ACCESS_TOKEN_TYPE = "access"
	}
}
