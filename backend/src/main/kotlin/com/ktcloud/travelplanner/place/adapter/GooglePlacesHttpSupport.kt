package com.ktcloud.travelplanner.place.adapter

import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import com.ktcloud.travelplanner.global.external.externalHttpRequestFactory
import com.ktcloud.travelplanner.global.external.hasExternalTimeoutCause
import org.springframework.web.client.ResourceAccessException

internal fun googlePlacesRequestFactory(properties: GooglePlacesProperties) =
	externalHttpRequestFactory(properties.connectTimeout, properties.readTimeout)

internal fun ResourceAccessException.toGooglePlacesException(): GooglePlacesException =
	if (hasExternalTimeoutCause()) GooglePlacesTimeoutException(this) else GooglePlacesProviderException(this)
