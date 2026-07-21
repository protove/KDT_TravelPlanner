package com.ktcloud.travelplanner.global.external

import org.springframework.http.client.JdkClientHttpRequestFactory
import java.net.http.HttpClient
import java.time.Duration
import java.util.concurrent.TimeoutException

fun externalHttpRequestFactory(
	connectTimeout: Duration,
	readTimeout: Duration,
): JdkClientHttpRequestFactory {
	val httpClient = HttpClient.newBuilder()
		.connectTimeout(connectTimeout)
		.build()
	return JdkClientHttpRequestFactory(httpClient).apply {
		setReadTimeout(readTimeout)
	}
}

fun Throwable.hasExternalTimeoutCause(): Boolean =
	generateSequence(this) { it.cause }
		.any { it is TimeoutException || it is java.net.http.HttpTimeoutException }
