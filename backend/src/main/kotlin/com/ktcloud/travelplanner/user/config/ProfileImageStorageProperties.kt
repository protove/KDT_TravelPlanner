package com.ktcloud.travelplanner.user.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties("app.storage.profile-image")
data class ProfileImageStorageProperties(
	val enabled: Boolean = false,
	val endpoint: String = "",
	val region: String = "ap-northeast-2",
	val accessKey: String = "",
	val secretKey: String = "",
	val bucket: String = "",
	val publicBaseUrl: String = "",
	val pathStyleAccessEnabled: Boolean = true,
	val uploadUrlTtl: Duration = Duration.ofMinutes(10),
)
