package com.ktcloud.travelplanner.auth.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.context.annotation.Primary
import org.springframework.http.client.JdkClientHttpRequestFactory
import org.springframework.web.client.RestClient
import java.net.http.HttpClient

@Configuration(proxyBeanMethods = false)
class OAuthHttpClientConfiguration {
	@Bean
	@Primary
	fun oauthRestClient(
		restClientBuilder: RestClient.Builder,
		properties: OAuthHttpClientProperties,
	): RestClient {
		val httpClient = HttpClient.newBuilder()
			.connectTimeout(properties.connectTimeout)
			.build()
		val requestFactory = JdkClientHttpRequestFactory(httpClient).apply {
			setReadTimeout(properties.readTimeout)
		}
		return restClientBuilder.clone()
			.requestFactory(requestFactory)
			.build()
	}
}
