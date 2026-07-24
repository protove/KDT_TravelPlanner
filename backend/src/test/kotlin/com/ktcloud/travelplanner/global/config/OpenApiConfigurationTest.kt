package com.ktcloud.travelplanner.global.config

import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import io.swagger.v3.oas.models.Operation
import io.swagger.v3.oas.models.parameters.Parameter
import org.junit.jupiter.api.Test
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.method.HandlerMethod
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull

class OpenApiConfigurationTest {
	private val configuration = OpenApiConfiguration()

	@Test
	fun `OpenAPI metadata defines the TravelPlanner JWT contract`() {
		val openApi = configuration.travelPlannerOpenApi()

		assertEquals(OpenApiConfiguration.API_TITLE, openApi.info.title)
		assertEquals(OpenApiConfiguration.API_DESCRIPTION, openApi.info.description)
		assertEquals(OpenApiConfiguration.API_VERSION, openApi.info.version)

		val bearerScheme = assertNotNull(
			openApi.components.securitySchemes[OpenApiConfiguration.SECURITY_SCHEME_NAME],
		)
		assertEquals("http", bearerScheme.type.toString().lowercase())
		assertEquals("bearer", bearerScheme.scheme)
		assertEquals("JWT", bearerScheme.bearerFormat)
		assertEquals(
			emptyList(),
			openApi.security.single()[OpenApiConfiguration.SECURITY_SCHEME_NAME],
		)
	}

	@Test
	fun `authentication principal customizer removes only the injected principal parameter`() {
		val fixture = OpenApiControllerFixture()
		val method = OpenApiControllerFixture::class.java.getDeclaredMethod(
			"getTravels",
			AuthenticatedUserPrincipal::class.java,
			String::class.java,
		)
		val operation = Operation().parameters(
			listOf(
				Parameter().name("principal"),
				Parameter().name("keyword"),
			),
		)

		val customizedOperation = configuration.authenticationPrincipalOperationCustomizer()
			.customize(operation, HandlerMethod(fixture, method))

		val parameterNames = assertNotNull(customizedOperation.parameters).map(Parameter::getName)
		assertFalse("principal" in parameterNames)
		assertEquals(listOf("keyword"), parameterNames)
	}
}

private class OpenApiControllerFixture {
	@Suppress("UNUSED_PARAMETER")
	fun getTravels(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		keyword: String,
	) = Unit
}
