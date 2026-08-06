package com.ktcloud.travelplanner

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.jdbc.core.JdbcTemplate

class PostgresRedisIntegrationTest : ContainerIntegrationTestSupport() {

	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Autowired
	private lateinit var redisTemplate: StringRedisTemplate

	@Test
	fun `PostgreSQL accepts a real query`() {
		val result = jdbcTemplate.queryForObject("SELECT 1", Int::class.java)

		assertEquals(1, result)
	}

	@Test
	fun `Redis stores reads and deletes a value`() {
		val key = "integration:smoke"
		try {
			redisTemplate.opsForValue().set(key, "ok")
			assertEquals("ok", redisTemplate.opsForValue().get(key))
		} finally {
			redisTemplate.delete(key)
		}

		assertEquals(false, redisTemplate.hasKey(key))
	}
}
