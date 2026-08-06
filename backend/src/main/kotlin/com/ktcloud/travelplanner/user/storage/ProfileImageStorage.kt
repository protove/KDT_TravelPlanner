package com.ktcloud.travelplanner.user.storage

import java.net.URI
import java.time.Duration

interface ProfileImageStorage {
	fun createUploadUrl(command: ProfileImageUploadCommand): URI

	fun getObjectMetadata(objectKey: String): ProfileImageObjectMetadata?
}

data class ProfileImageUploadCommand(
	val objectKey: String,
	val contentType: String,
	val fileSize: Long,
	val expiresIn: Duration,
)

data class ProfileImageObjectMetadata(
	val contentType: String?,
	val fileSize: Long,
)
