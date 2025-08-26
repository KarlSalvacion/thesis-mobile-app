/** @type {import('tailwindcss').Config} */
module.exports = {
  // NOTE: Update this to include the paths to all files that contain Nativewind classes.
  content: ["./App.tsx", "./src/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        bgColor1: 'rgb(249, 249, 252)',
        greenColor: 'rgb(37, 165, 120)',
        grayColor: 'rgb(240, 240, 240)',
        darkgrayColor: 'rgb(198, 199, 198)',
      },

      boxShadow: {
        'custom': '0 30px 50px rgba(51, 53, 46, 0.2)',
      },
    },
  },
  plugins: [],
}