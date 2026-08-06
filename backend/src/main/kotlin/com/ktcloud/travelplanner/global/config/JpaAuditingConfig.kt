package com.ktcloud.travelplanner.global.config

import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.data.auditing.DateTimeProvider
import org.springframework.data.jpa.repository.config.EnableJpaAuditing
import java.time.Clock
import java.time.Instant
import java.time.temporal.TemporalAccessor
import java.util.Optional

@Configuration
@EnableJpaAuditing(dateTimeProviderRef = "utcDateTimeProvider")
class JpaAuditingConfig {
	@Bean
	fun utcClock(): Clock = Clock.systemUTC()

	@Bean
	fun utcDateTimeProvider(
		@Qualifier("utcClock") clock: Clock,
	): DateTimeProvider = UtcDateTimeProvider(clock)
}

class UtcDateTimeProvider(
	private val clock: Clock,
) : DateTimeProvider {
	override fun getNow(): Optional<TemporalAccessor> =
		Optional.of<TemporalAccessor>(Instant.now(clock))
}
