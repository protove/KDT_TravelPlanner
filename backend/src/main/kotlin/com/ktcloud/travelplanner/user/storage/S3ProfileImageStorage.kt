package com.ktcloud.travelplanner.user.storage

import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.exception.ExternalServiceException
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import jakarta.annotation.PreDestroy
import org.springframework.stereotype.Component
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider
import software.amazon.awssdk.regions.Region
import software.amazon.awssdk.services.s3.S3Configuration
import software.amazon.awssdk.services.s3.model.PutObjectRequest
import software.amazon.awssdk.services.s3.presigner.S3Presigner
import software.amazon.awssdk.services.s3.presigner.model.PutObjectPresignRequest
import java.net.URI
import java.time.Duration

@Component
class S3ProfileImageStorage(
	private val properties: ProfileImageStorageProperties,
) : ProfileImageStorage {
	private val presigner = lazy(::createPresigner)

	override fun createUploadUrl(command: ProfileImageUploadCommand): URI {
		validateConfiguration()
		val putObjectRequest = PutObjectRequest.builder()
			.bucket(properties.bucket)
			.key(command.objectKey)
			.contentType(command.contentType)
			.contentLength(command.fileSize)
			.build()
		val presignRequest = PutObjectPresignRequest.builder()
			.signatureDuration(command.expiresIn)
			.putObjectRequest(putObjectRequest)
			.build()

		return try {
			presigner.value.presignPutObject(presignRequest).url().toURI()
		} catch (exception: Exception) {
			throw ProfileImageStorageException(exception)
		}
	}

	@PreDestroy
	fun close() {
		if (presigner.isInitialized()) {
			presigner.value.close()
		}
	}

	private fun createPresigner(): S3Presigner {
		val builder = S3Presigner.builder()
			.region(Region.of(properties.region))
			.serviceConfiguration(
				S3Configuration.builder()
					.pathStyleAccessEnabled(properties.pathStyleAccessEnabled)
					.build(),
			)
			.credentialsProvider(
				if (properties.accessKey.isNotBlank() && properties.secretKey.isNotBlank()) {
					StaticCredentialsProvider.create(
						AwsBasicCredentials.create(properties.accessKey, properties.secretKey),
					)
				} else {
					DefaultCredentialsProvider.builder().build()
				},
			)

		if (properties.endpoint.isNotBlank()) {
			builder.endpointOverride(URI.create(properties.endpoint))
		}
		return builder.build()
	}

	private fun validateConfiguration() {
		if (!properties.enabled) {
			throw ProfileImageStorageUnavailableException()
		}
		if (properties.bucket.isBlank() || properties.region.isBlank()) {
			throw ProfileImageStorageUnavailableException()
		}
		if (properties.accessKey.isBlank() != properties.secretKey.isBlank()) {
			throw ProfileImageStorageUnavailableException()
		}
		if (properties.uploadUrlTtl <= Duration.ZERO || properties.uploadUrlTtl > MAX_UPLOAD_URL_TTL) {
			throw ProfileImageStorageUnavailableException()
		}
	}

	companion object {
		private val MAX_UPLOAD_URL_TTL: Duration = Duration.ofDays(7)
	}
}

class ProfileImageStorageUnavailableException :
	ExternalServiceException(ErrorCode.EXTERNAL_STORAGE_ERROR, "프로필 이미지 저장소가 설정되지 않았습니다.")

class ProfileImageStorageException(
	cause: Throwable,
) : ExternalServiceException(ErrorCode.EXTERNAL_STORAGE_ERROR, cause = cause)
