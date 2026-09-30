// Country-State dropdown functionality
document.addEventListener("DOMContentLoaded", function() {
    const countrySelect = document.getElementById("country");
    const stateSelect = document.getElementById("state");

    // Only initialize if both elements exist
    if (countrySelect && stateSelect) {
        const states = {
            "US": [
                "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
                "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
                "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
                "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
                "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
                "New Hampshire", "New Jersey", "New Mexico", "New York",
                "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
                "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
                "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
                "West Virginia", "Wisconsin", "Wyoming"
            ],
            "CA": [
                "Alberta", "British Columbia", "Manitoba", "New Brunswick",
                "Newfoundland and Labrador", "Nova Scotia", "Ontario",
                "Prince Edward Island", "Quebec", "Saskatchewan"
            ]
        };

        countrySelect.addEventListener("change", function() {
            const selectedCountry = this.value;
            stateSelect.innerHTML = '<option value="">Select State</option>';

            if (selectedCountry && states[selectedCountry]) {
                states[selectedCountry].forEach(state => {
                    const option = document.createElement("option");
                    option.value = state;
                    option.textContent = state;
                    stateSelect.appendChild(option);
                });
            }
        });
    }
});

// Main Script - with proper null checks
document.addEventListener('DOMContentLoaded', function() {
    // VIN Input handling - with null check
    const vinInput = document.getElementById('vin');
    if (vinInput) {
        vinInput.addEventListener('input', function() {
            this.value = this.value.toUpperCase();
            if (this.value.length > 17) {
                this.value = this.value.slice(0, 17);
            }
        });
    }

    // Form validation - with null check
    const forms = document.querySelectorAll('form');
    if (forms.length > 0) {
        forms.forEach(form => {
            form.addEventListener('submit', function(e) {
                let valid = true;
                const inputs = this.querySelectorAll('input[required]');
                
                inputs.forEach(input => {
                    if (!input.value.trim()) {
                        valid = false;
                        input.style.borderColor = 'red';
                    } else {
                        input.style.borderColor = '';
                    }
                });

                if (!valid) {
                    e.preventDefault();
                    alert('Please fill in all required fields');
                }
            });
        });
    }

    // Payment form formatting - with null checks
    const cardInput = document.querySelector('input[placeholder="1234 1234 1234 1234"]');
    if (cardInput) {
        cardInput.addEventListener('input', function() {
            this.value = this.value.replace(/\D/g, '').replace(/(.{4})/g, '$1 ').trim();
            if (this.value.length > 19) {
                this.value = this.value.slice(0, 19);
            }
        });
    }

    const expiryInput = document.querySelector('input[placeholder="MM/YY"]');
    if (expiryInput) {
        expiryInput.addEventListener('input', function() {
            this.value = this.value.replace(/\D/g, '').replace(/(.{2})/, '$1/');
            if (this.value.length > 5) {
                this.value = this.value.slice(0, 5);
            }
        });
    }

    const cvcInput = document.querySelector('input[placeholder="CVC"]');
    if (cvcInput) {
        cvcInput.addEventListener('input', function() {
            this.value = this.value.replace(/\D/g, '');
            if (this.value.length > 3) {
                this.value = this.value.slice(0, 3);
            }
        });
    }

    // Initialize other functionalities
    initSlider();
    initAnimations();
    initTestimonialsSlider();
    initPageAnimations();
    initFAQAccordion();
    initCounterAnimations();
});

// Fixed Counter Animation
function initCounterAnimation() {
    const counters = document.querySelectorAll('.stat h3');
    const statsSection = document.querySelector('.stats');
    
    if (!counters.length || !statsSection) return;

    let animated = false;

    function startCounters() {
        if (animated) return;

        counters.forEach(counter => {
            let targetText = counter.getAttribute('data-target') || counter.textContent;
            const target = parseInt(targetText.replace(/[^0-9]/g, ''));
            const isPercentage = targetText.includes('%');
            const is24_7 = targetText.includes('24');
            const duration = 2000;
            const increment = target / (duration / 16);
            let current = 0;

            const updateCounter = () => {
                current += increment;
                if (current < target) {
                    if (is24_7) {
                        counter.textContent = '24/7';
                    } else if (isPercentage) {
                        counter.textContent = Math.ceil(current) + '%';
                    } else {
                        counter.textContent = Math.ceil(current).toLocaleString() + '+';
                    }
                    requestAnimationFrame(updateCounter);
                } else {
                    if (is24_7) {
                        counter.textContent = '24/7';
                    } else if (isPercentage) {
                        counter.textContent = target + '%';
                    } else {
                        counter.textContent = target.toLocaleString() + '+';
                    }
                }
            };

            if (is24_7) {
                counter.textContent = '24/7';
            } else if (isPercentage) {
                counter.textContent = '0%';
            } else {
                counter.textContent = '0+';
            }
            updateCounter();
        });

        animated = true;
    }

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                startCounters();
            }
        });
    }, { threshold: 0.5 });

    observer.observe(statsSection);
}

// Testimonials Slider with Auto Change
function initTestimonialsSlider() {
    const testimonials = document.querySelectorAll('.testimonial-card');
    const dotsContainer = document.querySelector('.testimonial-dots');
    
    if (testimonials.length <= 1) return;

    let currentTestimonial = 0;
    let testimonialInterval;

    if (dotsContainer && testimonials.length > 1) {
        dotsContainer.innerHTML = '';
        testimonials.forEach((_, index) => {
            const dot = document.createElement('div');
            dot.className = 'testimonial-dot' + (index === 0 ? ' active' : '');
            dot.addEventListener('click', () => {
                showTestimonial(index);
            });
            dotsContainer.appendChild(dot);
        });
    }

    function showTestimonial(index) {
        testimonials.forEach(testimonial => testimonial.classList.remove('active'));
        const dots = document.querySelectorAll('.testimonial-dot');
        currentTestimonial = (index + testimonials.length) % testimonials.length;
        testimonials[currentTestimonial].classList.add('active');

        if (dots.length > 0) {
            dots.forEach(dot => dot.classList.remove('active'));
            dots[currentTestimonial].classList.add('active');
        }
    }

    function nextTestimonial() {
        showTestimonial(currentTestimonial + 1);
    }

    function startTestimonialSlider() {
        stopTestimonialSlider();
        testimonialInterval = setInterval(nextTestimonial, 3000);
    }

    function stopTestimonialSlider() {
        clearInterval(testimonialInterval);
    }

    showTestimonial(0);
    startTestimonialSlider();

    const testimonialsSection = document.querySelector('.testimonials');
    if (testimonialsSection) {
        testimonialsSection.addEventListener('mouseenter', stopTestimonialSlider);
        testimonialsSection.addEventListener('mouseleave', startTestimonialSlider);
    }
}

// Enhanced Page Animations
function initPageAnimations() {
    const animatedElements = document.querySelectorAll('[data-aos]');
    if (animatedElements.length === 0) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const delay = entry.target.getAttribute('data-aos-delay') || 0;
                setTimeout(() => {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                    entry.target.style.transition = 'all 0.8s ease';
                }, parseInt(delay));
            }
        });
    }, { threshold: 0.1 });

    animatedElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(30px)';
        observer.observe(el);
    });
}

// FAQ Accordion
function initFAQAccordion() {
    const faqItems = document.querySelectorAll('.faq-item');
    if (faqItems.length === 0) return;

    faqItems.forEach(item => {
        const question = item.querySelector('.faq-question');
        if (question) {
            question.addEventListener('click', () => {
                item.classList.toggle('active');
                faqItems.forEach(otherItem => {
                    if (otherItem !== item) {
                        otherItem.classList.remove('active');
                    }
                });
            });
        }
    });
}

// Counter Animations for About & Contact
function initCounterAnimations() {
    const counters = document.querySelectorAll('[data-count]');
    const statsSection = document.querySelector('.stats');
    if (!counters.length || !statsSection) return;

    let started = false;

    function animateCounters() {
        if (started) return;
        started = true;

        counters.forEach(counter => {
            const target = +counter.getAttribute('data-count');
            let current = 0;
            const increment = target / 100;
            const updateCounter = () => {
                current += increment;
                if (current < target) {
                    counter.textContent = Math.ceil(current);
                    requestAnimationFrame(updateCounter);
                } else {
                    counter.textContent = target;
                }
            };
            updateCounter();
        });
    }

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                animateCounters();
            }
        });
    }, { threshold: 0.5 });

    observer.observe(statsSection);
}

// CTA Animation
function initCTAAnimation() {
    const ctaButton = document.querySelector('.cta .btn-primary');
    if (!ctaButton) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                ctaButton.classList.add('pulse');
            }
        });
    }, { threshold: 0.5 });

    observer.observe(ctaButton);
}

// Combine All Animations
function initAnimations() {
    initCounterAnimation();
    initTestimonialAnimation();
    initCTAAnimation();
}

function initTestimonialAnimation() {
    const testimonials = document.querySelector('.testimonials');
    if (!testimonials) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, { threshold: 0.3 });

    testimonials.style.opacity = '0';
    testimonials.style.transform = 'translateY(50px)';
    testimonials.style.transition = 'all 0.8s ease';
    observer.observe(testimonials);
}

// Hero Image Slider with null checks
function initSlider() {
    const slides = document.querySelectorAll('.slide');
    const dotsContainer = document.querySelector('.slider-dots');
    
    if (slides.length === 0) return;

    let currentSlide = 0;
    let slideInterval;

    function createDots() {
        if (!dotsContainer) return;
        dotsContainer.innerHTML = '';
        
        slides.forEach((_, index) => {
            const dot = document.createElement('div');
            dot.className = 'dot';
            dot.addEventListener('click', () => {
                stopSlider();
                showSlide(index);
                startSlider();
            });
            dotsContainer.appendChild(dot);
        });
    }

    function showSlide(n) {
        slides.forEach(slide => slide.classList.remove('active'));
        currentSlide = (n + slides.length) % slides.length;
        slides[currentSlide].classList.add('active');

        const dots = document.querySelectorAll('.dot');
        if (dots.length > 0) {
            dots.forEach(dot => dot.classList.remove('active'));
            dots[currentSlide].classList.add('active');
        }
    }

    function nextSlide() {
        showSlide(currentSlide + 1);
    }

    function startSlider() {
        stopSlider();
        slideInterval = setInterval(nextSlide, 2000);
    }

    function stopSlider() {
        clearInterval(slideInterval);
    }

    // Initialize only if elements exist
    const heroSection = document.querySelector('.hero');
    if (heroSection && slides.length > 1) {
        createDots();
        showSlide(currentSlide);
        startSlider();

        heroSection.addEventListener('mouseenter', stopSlider);
        heroSection.addEventListener('mouseleave', startSlider);
    }
}