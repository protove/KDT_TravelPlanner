package com.ktcloud.travelplanner.global.security

import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.web.SecurityFilterChain
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter

@Configuration
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@EnableMethodSecurity
class SecurityConfig(
	private val apiSecurityErrorHandler: ApiSecurityErrorHandler,
) {
	@Bean
	fun jwtAuthenticationFilter(
		jwtTokenService: JwtTokenService,
		userRepository: UserRepository,
	): JwtAuthenticationFilter = JwtAuthenticationFilter(
		jwtTokenService,
		userRepository,
		apiSecurityErrorHandler,
	)

	@Bean
	@Order(Ordered.LOWEST_PRECEDENCE)
	fun securityFilterChain(
		http: HttpSecurity,
		jwtAuthenticationFilter: JwtAuthenticationFilter,
	): SecurityFilterChain {
		http
			.csrf { it.disable() }
			.cors { }
			.formLogin { it.disable() }
			.httpBasic { it.disable() }
			.logout { it.disable() }
			.sessionManagement { it.sessionCreationPolicy(SessionCreationPolicy.STATELESS) }
			.exceptionHandling {
				it.authenticationEntryPoint(apiSecurityErrorHandler)
				it.accessDeniedHandler(apiSecurityErrorHandler)
			}
			.authorizeHttpRequests {
				it.requestMatchers(
					"/api/ping",
					"/api/v1/auth/oauth2/**",
					"/api/v1/auth/token/refresh",
					"/actuator/health/**",
				).permitAll()
					.requestMatchers("/api/**").authenticated()
					.anyRequest().permitAll()
			}
			.addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter::class.java)

		return http.build()
	}
}
