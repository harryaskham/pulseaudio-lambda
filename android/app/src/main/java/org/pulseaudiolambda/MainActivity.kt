package org.pulseaudiolambda

import android.os.Bundle
import android.widget.SeekBar
import androidx.appcompat.app.AppCompatActivity
import org.pulseaudiolambda.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var stemService: StemService

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        stemService = StemService(this)
        stemService.start()

        setupSlider(binding.drums, Stem.DRUMS)
        setupSlider(binding.guitar, Stem.GUITAR)
        setupSlider(binding.vocals, Stem.VOCALS)
        setupSlider(binding.other, Stem.OTHER)
    }

    private fun setupSlider(bar: SeekBar, stem: Stem) {
        bar.progress = 100
        bar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                stemService.setVolume(stem, progress / 100f)
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        })
    }

    override fun onDestroy() {
        super.onDestroy()
        stemService.stop()
    }
}

enum class Stem { DRUMS, GUITAR, VOCALS, OTHER }
