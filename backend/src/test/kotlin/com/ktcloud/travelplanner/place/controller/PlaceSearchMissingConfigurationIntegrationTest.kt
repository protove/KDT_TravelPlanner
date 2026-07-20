package com.ktcloud.travelplanner.place.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest(properties = ["app.external.google.places.api-key="])
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class PlaceSearchMissingConfigurationIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
) {
	@Test
	fun `application starts without key and search returns configuration error`() {
		val user = userRepository.saveAndFlush(
			User(
				provider = OAuthProvider.GOOGLE,
				providerUserId = "place-missing-${UUID.randomUUID()}",
			).also { it.completeProfile("place-missing-user", null, null) },
		)

		mockMvc.get("/api/v1/places/search") {
			header(
				HttpHeaders.AUTHORIZATION,
				"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}",
			)
			param("query", "도쿄 타워")
			param("countryCode", "JP")
		}.andExpect {
			status { isServiceUnavailable() }
			jsonPath("$.code", equalTo("GOOGLE_PLACES_NOT_CONFIGURED"))
		}
	}
}
