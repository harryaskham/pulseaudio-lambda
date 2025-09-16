package org.pulseaudiolambda

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.widget.SeekBar
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.pulseaudiolambda.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

    private val requestRecordAudio = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) requestProjection() }

    private val requestProjectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startStemService(result.resultCode, result.data!!)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Request permissions and start service
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestRecordAudio.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            requestProjection()
        }

        setupSlider(binding.drums, Stem.DRUMS)
        setupSlider(binding.bass, Stem.BASS)
        setupSlider(binding.vocals, Stem.VOCALS)
        setupSlider(binding.other, Stem.OTHER)
    }

    private fun requestProjection() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            val intent = mgr.createScreenCaptureIntent()
            requestProjectionLauncher.launch(intent)
        }
    }

    private fun startStemService(resultCode: Int, data: android.content.Intent) {
        val intent = Intent(this, StemService::class.java).apply {
            action = StemService.ACTION_START
            putExtra(StemService.EXTRA_RESULT_CODE, resultCode)
            putExtra(StemService.EXTRA_RESULT_DATA, data)
        }
        ContextCompat.startForegroundService(this, intent)
    }

    private fun sendVolume(stem: Stem, vol: Float) {
        val intent = Intent(this, StemService::class.java).apply {
            action = StemService.ACTION_SET_VOLUME
            putExtra(StemService.EXTRA_STEM, stem.name)
            putExtra(StemService.EXTRA_VOLUME, vol)
        }
        startService(intent)
    }

    private fun setupSlider(bar: SeekBar, stem: Stem) {
        bar.progress = 100
        bar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                sendVolume(stem, progress / 100f)
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        })
    }
}

enum class Stem { DRUMS, BASS, VOCALS, OTHER }
