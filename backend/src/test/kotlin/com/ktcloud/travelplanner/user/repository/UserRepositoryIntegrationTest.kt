package com.ktcloud.travelplanner.user.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.user.model.Gender
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import jakarta.persistence.EntityManager
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.jdbc.core.JdbcTemplate
import java.sql.Timestamp
import java.time.Instant
import java.util.UUID

class UserRepositoryIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var userRepository: UserRepository

	@Autowired
	private lateinit var entityManager: EntityManager

	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Test
	fun `Flyway creates user table and records migration`() {
		val tableCount = jdbcTemplate.queryForObject(
			"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'user_table'",
			Int::class.java,
		)
		val migrationCount = jdbcTemplate.queryForObject(
			"SELECT COUNT(*) FROM flyway_schema_history WHERE version = '1' AND success = TRUE",
			Int::class.java,
		)

		assertEquals(1, tableCount)
		assertEquals(1, migrationCount)
	}

	@Test
	fun `repository persists UUID enums profile and UTC auditing values`() {
		val user = createUser("google-persisted-1")
		user.completeProfile("persistedUser", Gender.UNSPECIFIED, 2001)

		val savedUser = userRepository.saveAndFlush(user)
		entityManager.clear()

		val foundUser = userRepository.findByProviderAndProviderUserId(
			OAuthProvider.GOOGLE,
			"google-persisted-1",
		)
		assertNotNull(savedUser.id)
		assertNotNull(savedUser.createdAt)
		assertNotNull(savedUser.updatedAt)
		assertEquals(savedUser.id, foundUser?.id)
		assertEquals(Gender.UNSPECIFIED, foundUser?.gender)
		assertTrue(foundUser?.isProfileCompleted == true)
	}

	@Test
	fun `provider identity and nickname constraints reject duplicates`() {
		val firstUser = createUser("duplicate-provider-id")
		firstUser.completeProfile("duplicateNickname", Gender.OTHER, 2000)
		userRepository.saveAndFlush(firstUser)

		assertThrows(DataIntegrityViolationException::class.java) {
			userRepository.saveAndFlush(createUser("duplicate-provider-id"))
		}

		val duplicateNicknameUser = User(
			provider = OAuthProvider.NAVER,
			providerUserId = "naver-unique-id",
		)
		duplicateNicknameUser.completeProfile("duplicateNickname", null, null)
		assertThrows(DataIntegrityViolationException::class.java) {
			userRepository.saveAndFlush(duplicateNicknameUser)
		}
	}

	@Test
	fun `database rejects unsupported OAuth provider`() {
		val now = Timestamp.from(Instant.now())

		assertThrows(DataIntegrityViolationException::class.java) {
			jdbcTemplate.update(
				"""
				INSERT INTO user_table (
				    id, provider, provider_user_id, profile_completed, created_at, updated_at
				) VALUES (?, ?, ?, FALSE, ?, ?)
				""".trimIndent(),
				UUID.randomUUID(),
				"GITHUB",
				"unsupported-provider-user",
				now,
				now,
			)
		}
	}

	@Test
	fun `soft deleted user is excluded from repository queries`() {
		val user = userRepository.saveAndFlush(createUser("soft-deleted-user"))
		val userId = requireNotNull(user.id)

		user.softDelete(TestFixtures.FIXED_INSTANT)
		userRepository.saveAndFlush(user)
		entityManager.clear()

		assertFalse(userRepository.findById(userId).isPresent)
		assertNull(
			userRepository.findByProviderAndProviderUserId(
				OAuthProvider.GOOGLE,
				"soft-deleted-user",
			),
		)
	}

	private fun createUser(providerUserId: String): User = User(
		provider = OAuthProvider.GOOGLE,
		providerUserId = providerUserId,
		email = "$providerUserId@example.com",
		name = "Travel User",
	)
}
