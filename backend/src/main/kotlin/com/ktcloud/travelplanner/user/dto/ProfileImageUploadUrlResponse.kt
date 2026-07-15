package com.ktcloud.travelplanner.user.dto

import java.net.URI
import java.time.Instant

data class ProfileImageUploadUrlResponse(
	val uploadUrl: URI,
	val objectKey: String,
	val expiresAt: Instant,
)
