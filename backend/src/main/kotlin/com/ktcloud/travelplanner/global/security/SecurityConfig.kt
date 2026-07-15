package com.ktcloud.travelplanner.global.security

import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.web.SecurityFilterChain

@Configuration
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
class SecurityConfig(
	private val apiSecurityErrorHandler: ApiSecurityErrorHandler,
) {
	@Bean
	@Order(Ordered.LOWEST_PRECEDENCE)
	fun securityFilterChain(http: HttpSecurity): SecurityFilterChain {
		http
			.csrf { it.disable() }
			.formLogin { it.disable() }
			.httpBasic { it.disable() }
			.logout { it.disable() }
			.sessionManagement { it.sessionCreationPolicy(SessionCreationPolicy.STATELESS) }
			.exceptionHandling {
				it.authenticationEntryPoint(apiSecurityErrorHandler)
				it.accessDeniedHandler(apiSecurityErrorHandler)
			}
			.authorizeHttpRequests { it.anyRequest().permitAll() }

		return http.build()
	}
}
