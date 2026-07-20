package com.ktcloud.travelplanner.location.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.location.model.Country
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.BeforeEach
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
import java.math.BigDecimal
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class LocationControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val countryRepository: CountryRepository,
	@Autowired private val cityRepository: CityRepository,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
) {
	private lateinit var accessToken: String

	@BeforeEach
	fun setUpCatalog() {
		cityRepository.deleteAllInBatch()
		countryRepository.deleteAllInBatch()

		val japan = countryRepository.save(Country(1, "JP", "일본", "Japan", 1, true))
		val korea = countryRepository.save(Country(2, "KR", "대한민국", "South Korea", 0, true))
		countryRepository.save(Country(3, "ZZ", "숨김 국가", "Hidden Country", 2, false))

		cityRepository.save(City(10, japan, "도쿄", "Tokyo", displayOrder = 1))
		cityRepository.save(
			City(
				id = 11,
				country = japan,
				nameKo = "오사카",
				nameEn = "Osaka",
				latitude = BigDecimal("34.693700"),
				longitude = BigDecimal("135.502300"),
				displayOrder = 0,
			),
		)
		cityRepository.save(City(12, japan, "숨김 도시", "Hidden City", displayOrder = 2, isActive = false))
		cityRepository.save(City(20, korea, "서울", "Seoul"))

		val user = userRepository.saveAndFlush(
			User(OAuthProvider.GOOGLE, "location-${UUID.randomUUID()}"),
		)
		accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value
	}

	@Test
	fun `returns active countries and belonging cities in display order`() {
		mockMvc.get("/api/v1/countries") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(2))
				jsonPath("$.data[0].countryId", equalTo(2))
				jsonPath("$.data[0].code", equalTo("KR"))
				jsonPath("$.data[1].countryId", equalTo(1))
			}

		mockMvc.get("/api/v1/countries/1/cities") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(2))
				jsonPath("$.data[0].cityId", equalTo(11))
				jsonPath("$.data[0].countryId", equalTo(1))
				jsonPath("$.data[0].nameEn", equalTo("Osaka"))
				jsonPath("$.data[0].latitude", equalTo(34.693700))
				jsonPath("$.data[1].cityId", equalTo(10))
			}
	}

	@Test
	fun `inactive or absent country returns not found`() {
		listOf(3, 99).forEach { countryId ->
			mockMvc.get("/api/v1/countries/$countryId/cities") {
				header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			}
				.andExpect {
					status { isNotFound() }
					jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
				}
		}
	}

	@Test
	fun `location catalog requires authentication`() {
		mockMvc.get("/api/v1/countries")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}
}
