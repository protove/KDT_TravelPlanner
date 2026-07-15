package com.ktcloud.travelplanner.testsupport

import org.springframework.boot.test.context.TestConfiguration
import org.springframework.boot.testcontainers.service.connection.ServiceConnection
import org.springframework.context.annotation.Bean
import org.testcontainers.containers.GenericContainer
import org.testcontainers.containers.PostgreSQLContainer
import org.testcontainers.utility.DockerImageName

@TestConfiguration(proxyBeanMethods = false)
class TestcontainersConfiguration {

	@Bean
	@ServiceConnection
	fun postgresContainer(): PostgreSQLContainer<*> =
		PostgreSQLContainer<Nothing>(DockerImageName.parse("postgres:17.10-alpine"))

	@Bean
	@ServiceConnection(name = "redis")
	fun redisContainer(): GenericContainer<*> =
		GenericContainer<Nothing>(DockerImageName.parse("redis:7.4.9-alpine"))
			.withExposedPorts(6379)
}
