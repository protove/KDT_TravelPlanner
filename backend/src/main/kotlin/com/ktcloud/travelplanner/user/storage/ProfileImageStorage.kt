package com.ktcloud.travelplanner.user.storage

import java.net.URI
import java.time.Duration

fun interface ProfileImageStorage {
	fun createUploadUrl(command: ProfileImageUploadCommand): URI
}

data class ProfileImageUploadCommand(
	val objectKey: String,
	val contentType: String,
	val fileSize: Long,
	val expiresIn: Duration,
)
