package com.ktcloud.travelplanner.global.config

import io.swagger.v3.oas.models.Components
import io.swagger.v3.oas.models.OpenAPI
import io.swagger.v3.oas.models.info.Info
import io.swagger.v3.oas.models.security.SecurityRequirement
import io.swagger.v3.oas.models.security.SecurityScheme
import org.springdoc.core.customizers.OperationCustomizer
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.DefaultParameterNameDiscoverer
import org.springframework.security.core.annotation.AuthenticationPrincipal

@Configuration(proxyBeanMethods = false)
class OpenApiConfiguration {
	private val parameterNameDiscoverer = DefaultParameterNameDiscoverer()

	@Bean
	fun travelPlannerOpenApi(): OpenAPI = OpenAPI()
		.info(
			Info()
				.title(API_TITLE)
				.description(API_DESCRIPTION)
				.version(API_VERSION),
		)
		.components(
			Components().addSecuritySchemes(
				SECURITY_SCHEME_NAME,
				SecurityScheme()
					.type(SecurityScheme.Type.HTTP)
					.scheme(BEARER_SCHEME)
					.bearerFormat(BEARER_FORMAT),
			),
		)
		.addSecurityItem(SecurityRequirement().addList(SECURITY_SCHEME_NAME))

	@Bean
	fun authenticationPrincipalOperationCustomizer(): OperationCustomizer =
		OperationCustomizer { operation, handlerMethod ->
			val authenticationPrincipalParameterNames = handlerMethod.methodParameters
				.filter { it.hasParameterAnnotation(AuthenticationPrincipal::class.java) }
				.mapNotNull {
					it.initParameterNameDiscovery(parameterNameDiscoverer)
					it.parameterName
				}
				.toSet()

			if (authenticationPrincipalParameterNames.isNotEmpty()) {
				operation.parameters = operation.parameters
					?.filterNot { it.name in authenticationPrincipalParameterNames }
			}
			operation
		}

	companion object {
		const val API_TITLE = "KDT-TravelPlanner API"
		const val API_DESCRIPTION = "KDT-TravelPlanner backend API"
		const val API_VERSION = "v1"
		const val SECURITY_SCHEME_NAME = "bearerAuth"
		private const val BEARER_SCHEME = "bearer"
		private const val BEARER_FORMAT = "JWT"
	}
}
