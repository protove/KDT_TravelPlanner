package com.ktcloud.travelplanner.global.security

import com.ktcloud.travelplanner.global.logging.RequestIdGenerator
import com.ktcloud.travelplanner.global.logging.RequestLoggingFilter
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.boot.test.context.TestConfiguration
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Import
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.test.context.support.WithMockUser
import org.springframework.security.web.SecurityFilterChain
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@ActiveProfiles("test")
@WebMvcTest(ApiSecurityTestController::class)
@Import(
	RequestLoggingFilter::class,
	ApiSecurityErrorHandler::class,
	ProtectedSecurityConfiguration::class,
)
class ApiSecurityErrorIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
) {
	@Test
	fun `unauthenticated request returns common 401 response`() {
		mockMvc.get("/test/security/protected") {
			header(RequestIdGenerator.HEADER_NAME, "authentication-request")
		}
			.andExpect {
				status { isUnauthorized() }
				header { string(RequestIdGenerator.HEADER_NAME, "authentication-request") }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
				jsonPath("$.message", equalTo("인증이 필요합니다."))
				jsonPath("$.requestId", equalTo("authentication-request"))
				jsonPath("$.fieldErrors") { doesNotExist() }
			}
	}

	@Test
	@WithMockUser(roles = ["USER"])
	fun `unauthorized role returns common 403 response`() {
		mockMvc.get("/test/security/admin") {
			header(RequestIdGenerator.HEADER_NAME, "authorization-request")
		}
			.andExpect {
				status { isForbidden() }
				header { string(RequestIdGenerator.HEADER_NAME, "authorization-request") }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
				jsonPath("$.message", equalTo("접근 권한이 없습니다."))
				jsonPath("$.requestId", equalTo("authorization-request"))
			}
	}

}

@RestController
@RequestMapping("/test/security")
class ApiSecurityTestController {
	@GetMapping("/protected")
	fun protectedEndpoint(): String = "protected"

	@GetMapping("/admin")
	fun adminEndpoint(): String = "admin"
}

@TestConfiguration(proxyBeanMethods = false)
class ProtectedSecurityConfiguration {
	@Bean
	fun protectedSecurityFilterChain(
		http: HttpSecurity,
		apiSecurityErrorHandler: ApiSecurityErrorHandler,
	): SecurityFilterChain {
		http
			.securityMatcher("/test/security/**")
			.csrf { it.disable() }
			.exceptionHandling {
				it.authenticationEntryPoint(apiSecurityErrorHandler)
				it.accessDeniedHandler(apiSecurityErrorHandler)
			}
			.authorizeHttpRequests {
				it.requestMatchers("/test/security/admin").hasRole("ADMIN")
				it.anyRequest().authenticated()
			}
		return http.build()
	}
}
