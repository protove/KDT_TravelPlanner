package com.ktcloud.travelplanner

import org.junit.jupiter.api.Test
import org.springframework.boot.test.context.SpringBootTest

@SpringBootTest(
	classes = [TravelPlannerBackendApplication::class],
	webEnvironment = SpringBootTest.WebEnvironment.NONE,
	properties = [
		"spring.autoconfigure.exclude=" +
			"org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration," +
			"org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration," +
			"org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration",
	],
)
class TravelPlannerBackendApplicationTests {

	@Test
	fun `Spring context starts from TravelPlanner application`() = Unit
}
