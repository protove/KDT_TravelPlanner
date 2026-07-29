package com.ktcloud.travelplanner.user.storage

import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.exception.ExternalServiceException
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import jakarta.annotation.PreDestroy
import org.springframework.stereotype.Component
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials
import software.amazon.awssdk.auth.credentials.AwsCredentialsProvider
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider
import software.amazon.awssdk.regions.Region
import software.amazon.awssdk.services.s3.S3Client
import software.amazon.awssdk.services.s3.S3Configuration
import software.amazon.awssdk.services.s3.model.HeadObjectRequest
import software.amazon.awssdk.services.s3.model.PutObjectRequest
import software.amazon.awssdk.services.s3.model.S3Exception
import software.amazon.awssdk.services.s3.presigner.S3Presigner
import software.amazon.awssdk.services.s3.presigner.model.PutObjectPresignRequest
import java.net.URI
import java.time.Duration

@Component
class S3ProfileImageStorage(
	private val properties: ProfileImageStorageProperties,
) : ProfileImageStorage {
	private val presigner = lazy(::createPresigner)
	private val storageClient = lazy(::createStorageClient)

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

	override fun getObjectMetadata(objectKey: String): ProfileImageObjectMetadata? {
		validateConfiguration()
		val request = HeadObjectRequest.builder()
			.bucket(properties.bucket)
			.key(objectKey)
			.build()
		val response = try {
			storageClient.value.headObject(request)
		} catch (exception: S3Exception) {
			if (exception.statusCode() == NOT_FOUND_STATUS) {
				return null
			}
			throw ProfileImageStorageException(exception)
		} catch (exception: Exception) {
			throw ProfileImageStorageException(exception)
		}

		return ProfileImageObjectMetadata(
			contentType = response.contentType(),
			fileSize = response.contentLength(),
		)
	}

	@PreDestroy
	fun close() {
		if (presigner.isInitialized()) {
			presigner.value.close()
		}
		if (storageClient.isInitialized()) {
			storageClient.value.close()
		}
	}

	private fun createPresigner(): S3Presigner {
		val builder = S3Presigner.builder()
			.region(Region.of(properties.region))
			.serviceConfiguration(createServiceConfiguration())
			.credentialsProvider(createCredentialsProvider())

		if (properties.endpoint.isNotBlank()) {
			builder.endpointOverride(URI.create(properties.endpoint))
		}
		return builder.build()
	}

	private fun createStorageClient(): S3Client {
		val builder = S3Client.builder()
			.region(Region.of(properties.region))
			.serviceConfiguration(createServiceConfiguration())
			.credentialsProvider(createCredentialsProvider())

		if (properties.endpoint.isNotBlank()) {
			builder.endpointOverride(URI.create(properties.endpoint))
		}
		return builder.build()
	}

	private fun createServiceConfiguration(): S3Configuration =
		S3Configuration.builder()
			.pathStyleAccessEnabled(properties.pathStyleAccessEnabled)
			.build()

	private fun createCredentialsProvider(): AwsCredentialsProvider =
		if (properties.accessKey.isNotBlank() && properties.secretKey.isNotBlank()) {
			StaticCredentialsProvider.create(
				AwsBasicCredentials.create(properties.accessKey, properties.secretKey),
			)
		} else {
			DefaultCredentialsProvider.builder().build()
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
		private const val NOT_FOUND_STATUS = 404
		private val MAX_UPLOAD_URL_TTL: Duration = Duration.ofDays(7)
	}
}

class ProfileImageStorageUnavailableException :
	ExternalServiceException(ErrorCode.EXTERNAL_STORAGE_ERROR, "프로필 이미지 저장소가 설정되지 않았습니다.")

class ProfileImageStorageException(
	cause: Throwable,
) : ExternalServiceException(ErrorCode.EXTERNAL_STORAGE_ERROR, cause = cause)
