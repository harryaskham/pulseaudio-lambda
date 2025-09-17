package org.pulseaudiolambda

import android.content.Context
import android.media.*
import android.media.projection.MediaProjection
import kotlinx.coroutines.*
import kotlin.math.min
import org.pytorch.IValue
import org.pytorch.Module
import org.pytorch.Tensor

/**
 * Core audio capture + inference + mixing engine.
 * Runs on a background coroutine and exposes volume controls per stem.
 */
class StemEngine(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    enum class State { IDLE, RUNNING }

    data class Metrics(
        var modelLoaded: Boolean = false,
        var modelLoadMs: Long = 0,
        var modelName: String = "",
        var modelBytes: Long = 0,
        var totalProcessedFrames: Long = 0,
        var lastInferenceMs: Long = 0,
        var error: String? = null,
    )

    interface Listener {
        fun onMetrics(state: State, metrics: Metrics)
    }

    private val volumes = mutableMapOf(
        Stem.DRUMS to 1f,
        Stem.BASS to 1f,
        Stem.VOCALS to 1f,
        Stem.OTHER to 1f,
    )

    private var module: Module? = null
    private var job: Job? = null
    @Volatile private var state: State = State.IDLE
    @Volatile private var listener: Listener? = null
    private val metrics = Metrics()

    fun setListener(l: Listener?) { listener = l }

    fun setVolume(stem: Stem, volume: Float) { volumes[stem] = volume.coerceIn(0f, 1f) }

    fun getState(): State = state

    fun start(mediaProjection: MediaProjection): Boolean {
        if (state == State.RUNNING) return true

        // Load TorchScript module from assets -> files dir
        val loadStart = android.os.SystemClock.elapsedRealtime()
        val modelName = "separation.pt"
        val path = try { assetFilePath(modelName) } catch (t: Throwable) {
            metrics.error = "Missing asset: $modelName"
            listener?.onMetrics(state, metrics)
            return false
        }
        val file = java.io.File(path)
        metrics.modelName = modelName
        metrics.modelBytes = file.length()
        if (!file.exists() || file.length() < 1024 * 10) {
            metrics.error = "Model asset invalid: ${file.length()} bytes at ${file.name}"
            listener?.onMetrics(state, metrics)
            return false
        }
        module = try {
            Module.load(path)
        } catch (t: Throwable) {
            metrics.error = (t.message ?: "Model load failed")
            null
        }
        metrics.modelLoaded = module != null
        metrics.modelLoadMs = android.os.SystemClock.elapsedRealtime() - loadStart
        listener?.onMetrics(state, metrics)
        if (module == null) return false

        val sampleRate = 44100
        val encoding = AudioFormat.ENCODING_PCM_16BIT
        val inMask = AudioFormat.CHANNEL_IN_STEREO
        val outMask = AudioFormat.CHANNEL_OUT_STEREO

        val config = AudioPlaybackCaptureConfiguration.Builder(mediaProjection)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .build()

        val inputFormat = AudioFormat.Builder()
            .setEncoding(encoding)
            .setSampleRate(sampleRate)
            .setChannelMask(inMask)
            .build()

        val minBufBytes = AudioRecord.getMinBufferSize(sampleRate, inMask, encoding)
            .coerceAtLeast(4096)

        val recorder = AudioRecord.Builder()
            .setAudioPlaybackCaptureConfig(config)
            .setAudioFormat(inputFormat)
            .setBufferSizeInBytes(minBufBytes)
            .build()

        val player = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(encoding)
                    .setSampleRate(sampleRate)
                    .setChannelMask(outMask)
                    .build()
            )
            .setBufferSizeInBytes(minBufBytes)
            .build()

        val chunkSize = 8192 // samples per channel per chunk (must match TorchScript trace example length)
        val overlap = 1024   // overlap samples per chunk
        val frameSize = 2 /*bytes*/ * 2 /*stereo*/

        job = scope.launch(Dispatchers.Default) {
            val overlapBufferL = FloatArray(overlap)
            val overlapBufferR = FloatArray(overlap)
            val inputShorts = ShortArray(minBufBytes / 2)

            recorder.startRecording()
            player.play()
            state = State.RUNNING
            listener?.onMetrics(state, metrics)
            try {
                // Sliding window buffers
                val windowL = FloatArray(chunkSize)
                val windowR = FloatArray(chunkSize)
                var pendingL = 0
                var pendingR = 0

                while (isActive) {
                    val read = recorder.read(inputShorts, 0, inputShorts.size)
                    if (read <= 0) continue

                    // Deinterleave to float
                    var i = 0
                    while (i < read) {
                        val l = inputShorts[i].toFloat() / 32768f
                        val r = inputShorts[i + 1].toFloat() / 32768f
                        if (pendingL < windowL.size) windowL[pendingL++] = l
                        if (pendingR < windowR.size) windowR[pendingR++] = r
                        i += 2
                    }

                    // When enough for one chunk, build overlapped chunk and process
                    while (pendingL >= chunkSize && pendingR >= chunkSize) {
                        // Build chunk with previous overlap at the front
                        val chunkL = FloatArray(chunkSize)
                        val chunkR = FloatArray(chunkSize)
                        // Copy prev overlap
                        System.arraycopy(overlapBufferL, 0, chunkL, 0, overlap)
                        System.arraycopy(overlapBufferR, 0, chunkR, 0, overlap)
                        // Copy new samples
                        System.arraycopy(windowL, 0, chunkL, overlap, chunkSize - overlap)
                        System.arraycopy(windowR, 0, chunkR, overlap, chunkSize - overlap)

                        val inferStart = android.os.SystemClock.elapsedRealtime()
                        val out = processStereo(chunkL, chunkR)
                        metrics.lastInferenceMs = android.os.SystemClock.elapsedRealtime() - inferStart

                        // Output only hop size (exclude the leading overlap)
                        val hop = chunkSize - overlap
                        val outShorts = ShortArray(hop * 2)
                        var o = 0
                        var j = overlap
                        while (j < chunkSize) {
                            val l = (out.first[j].coerceIn(-1f, 1f) * 32768f).toInt().coerceIn(-32768, 32767).toShort()
                            val r = (out.second[j].coerceIn(-1f, 1f) * 32768f).toInt().coerceIn(-32768, 32767).toShort()
                            outShorts[o++] = l
                            outShorts[o++] = r
                            j++
                        }
                        player.write(outShorts, 0, outShorts.size)

                        // Save tail for next overlap
                        System.arraycopy(chunkL, hop, overlapBufferL, 0, overlap)
                        System.arraycopy(chunkR, hop, overlapBufferR, 0, overlap)

                        // Slide window by hop size
                        System.arraycopy(windowL, hop, windowL, 0, pendingL - hop)
                        System.arraycopy(windowR, hop, windowR, 0, pendingR - hop)
                        pendingL -= hop
                        pendingR -= hop
                        metrics.totalProcessedFrames += hop.toLong()
                        listener?.onMetrics(state, metrics)
                    }
                }
            } finally {
                state = State.IDLE
                listener?.onMetrics(state, metrics)
                try { recorder.stop() } catch (_: Throwable) {}
                try { player.stop() } catch (_: Throwable) {}
                recorder.release()
                player.release()
            }
        }

        return true
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    private fun processStereo(left: FloatArray, right: FloatArray): Pair<FloatArray, FloatArray> {
        val t = left.size

        // Prepare input as [1, 2, T] with channel-major contiguous layout
        val inputArray = FloatArray(2 * t)
        System.arraycopy(left, 0, inputArray, 0, t)
        System.arraycopy(right, 0, inputArray, t, t)
        val input = Tensor.fromBlob(inputArray, longArrayOf(1, 2, t.toLong()))

        val iv = try { module?.forward(IValue.from(input)) } catch (_: Throwable) { null } ?: return Pair(left, right)

        // Expected model output: [1, 4, 2, T] (batch, stems, channels, time)
        // Mix by applying per‑stem volume on dim-1 and summing over stems → [1, 2, T] → stereo [2, T].
        val mix = mixStemsStereo(iv, t) ?: return Pair(left, right)
        return Pair(mix.first, mix.second)
    }

    // Mix stems directly from a TorchScript output into stereo [L[], R[]]
    // Supports [1,4,2,T] (preferred) and [4,2,T].
    private fun mixStemsStereo(iv: IValue, t: Int): Pair<FloatArray, FloatArray>? {
        val vols = floatArrayOf(
            volumes[Stem.DRUMS] ?: 1f,
            volumes[Stem.BASS] ?: 1f,
            volumes[Stem.VOCALS] ?: 1f,
            volumes[Stem.OTHER] ?: 1f,
        )

        if (iv.isTensor) {
            val out = iv.toTensor()
            val shape = out.shape()
            val data = out.dataAsFloatArray

            if (shape.size == 4 && shape[0].toInt() == 1 && shape[1].toInt() == 4 && shape[2].toInt() == 2 && shape[3].toInt() == t) {
                val mixL = FloatArray(t)
                val mixR = FloatArray(t)
                var base = 0
                for (s in 0 until 4) {
                    val v = vols[s]
                    val lOff = base
                    val rOff = base + t
                    var j = 0
                    while (j < t) {
                        mixL[j] += data[lOff + j] * v
                        mixR[j] += data[rOff + j] * v
                        j++
                    }
                    base += 2 * t
                }
                return Pair(mixL, mixR)
            }

            if (shape.size == 3 && shape[0].toInt() == 4 && shape[1].toInt() == 2 && shape[2].toInt() == t) {
                val mixL = FloatArray(t)
                val mixR = FloatArray(t)
                var base = 0
                for (s in 0 until 4) {
                    val v = vols[s]
                    val lOff = base
                    val rOff = base + t
                    var j = 0
                    while (j < t) {
                        mixL[j] += data[lOff + j] * v
                        mixR[j] += data[rOff + j] * v
                        j++
                    }
                    base += 2 * t
                }
                return Pair(mixL, mixR)
            }
            return null
        }

        // List/Tuple of 4 tensors of shape [2, T]
        val lv: Array<IValue> = if (iv.isList) iv.toList() else if (iv.isTuple) iv.toTuple() else emptyArray()
        if (lv.size == 4) {
            val mixL = FloatArray(t)
            val mixR = FloatArray(t)
            for (s in 0 until 4) {
                val v = vols[s]
                val tensor = lv[s].toTensor()
                val shape = tensor.shape()
                if (!(shape.size == 2 && shape[0].toInt() == 2 && shape[1].toInt() == t)) return null
                val data = tensor.dataAsFloatArray
                val lOff = 0
                val rOff = t
                var j = 0
                while (j < t) {
                    mixL[j] += data[lOff + j] * v
                    mixR[j] += data[rOff + j] * v
                    j++
                }
            }
            return Pair(mixL, mixR)
        }

        return null
    }

    private fun assetFilePath(assetName: String): String {
        val file = java.io.File(context.filesDir, assetName)
        // Always refresh copy from APK asset to avoid stale LFS pointers from previous installs.
        // If asset is missing, this will throw and be handled by caller.
        context.assets.open(assetName).use { input ->
            java.io.FileOutputStream(file, false).use { output ->
                input.copyTo(output)
            }
        }
        return file.absolutePath
    }
}
