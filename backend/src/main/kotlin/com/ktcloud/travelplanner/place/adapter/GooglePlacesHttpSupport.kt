package com.ktcloud.travelplanner.place.adapter

import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import org.springframework.http.client.JdkClientHttpRequestFactory
import org.springframework.web.client.ResourceAccessException
import java.net.http.HttpClient
import java.util.concurrent.TimeoutException

internal fun googlePlacesRequestFactory(properties: GooglePlacesProperties): JdkClientHttpRequestFactory {
	val httpClient = HttpClient.newBuilder()
		.connectTimeout(properties.connectTimeout)
		.build()
	return JdkClientHttpRequestFactory(httpClient).apply {
		setReadTimeout(properties.readTimeout)
	}
}

internal fun ResourceAccessException.toGooglePlacesException(): GooglePlacesException =
	if (hasTimeoutCause()) GooglePlacesTimeoutException(this) else GooglePlacesProviderException(this)

private fun Throwable.hasTimeoutCause(): Boolean =
	generateSequence(this) { it.cause }.any { it is TimeoutException || it is java.net.http.HttpTimeoutException }
